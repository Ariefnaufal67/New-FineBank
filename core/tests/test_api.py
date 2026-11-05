from datetime import timedelta

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Bill, Category, Expense, User


def mk(email, role='user', password='password123'):
    return User.objects.create_user(username=email, email=email, name=email.split('@')[0], password=password, role=role)


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.c = APIClient()

    def login(self, email, password='password123'):
        r = self.c.post('/api/auth/login', {'email': email, 'password': password}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.c.credentials(HTTP_AUTHORIZATION='Bearer ' + r.json()['data']['token'])
        return r.json()['data']


class AuthTests(Base):
    def test_register_login_me(self):
        r = self.c.post('/api/auth/register', {'name': 'Budi', 'email': 'b@x.com', 'password': 'rahasia123'}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertNotIn('password', r.json()['data']['user'])
        self.assertEqual(r.json()['data']['user']['role'], 'user')
        d = self.login('b@x.com', 'rahasia123')
        me = self.c.get('/api/auth/me')
        self.assertEqual(me.json()['data']['email'], 'b@x.com')
        self.assertTrue(d['token'])

    def test_duplicate_email_409(self):
        mk('a@x.com')
        r = self.c.post('/api/auth/register', {'name': 'Aa', 'email': 'a@x.com', 'password': 'rahasia123'}, format='json')
        self.assertEqual(r.status_code, 409)

    def test_validation_422_shape(self):
        r = self.c.post('/api/auth/register', {'name': 'A', 'email': 'bukan-email', 'password': '1'}, format='json')
        self.assertEqual(r.status_code, 400)
        j = r.json()
        self.assertFalse(j['success'])
        self.assertEqual(j['message'], 'Validasi gagal')
        self.assertTrue(j['errors'])

    def test_wrong_password_401(self):
        mk('a@x.com')
        r = self.c.post('/api/auth/login', {'email': 'a@x.com', 'password': 'salah-salah'}, format='json')
        self.assertEqual(r.status_code, 401)

    def test_protected_requires_token(self):
        self.assertEqual(self.c.get('/api/expenses').status_code, 401)
        self.c.credentials(HTTP_AUTHORIZATION='Bearer sampah')
        self.assertEqual(self.c.get('/api/expenses').status_code, 401)

    def test_auth_throttle(self):
        codes = [self.c.post('/api/auth/login', {'email': 'n@x.com', 'password': 'salah-salah'}, format='json').status_code
                 for _ in range(12)]
        self.assertEqual(codes[:10], [401] * 10)
        self.assertEqual(codes[10], 429)


class CrudTests(Base):
    def setUp(self):
        super().setUp()
        self.u1, self.u2 = mk('u1@x.com'), mk('u2@x.com')
        self.admin = mk('admin@x.com', 'admin')
        self.sa = mk('super@x.com', 'superadmin')

    def test_category_crud_and_duplicate(self):
        self.login('u1@x.com')
        r = self.c.post('/api/categories', {'name': 'Makanan'}, format='json')
        self.assertEqual(r.status_code, 201)
        cid = r.json()['data']['id']
        self.assertEqual(self.c.post('/api/categories', {'name': 'Makanan'}, format='json').status_code, 409)
        self.assertEqual(self.c.put(f'/api/categories/{cid}', {'name': 'Food'}, format='json').json()['data']['name'], 'Food')
        self.assertEqual(self.c.delete(f'/api/categories/{cid}').status_code, 204)
        self.assertEqual(self.c.get('/api/categories').json()['data'], [])

    def test_expense_crud_and_isolation(self):
        self.login('u1@x.com')
        cat = self.c.post('/api/categories', {'name': 'Makanan'}, format='json').json()['data']['id']
        r = self.c.post('/api/expenses', {'title': 'Kopi', 'amount': 18000, 'date': '2026-09-01', 'categoryId': cat}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        eid = r.json()['data']['id']
        self.assertEqual(r.json()['data']['category']['name'], 'Makanan')
        self.assertEqual(self.c.get(f'/api/expenses/{eid}').status_code, 200)
        pr = self.c.put(f'/api/expenses/{eid}', {'amount': 20000}, format='json')
        self.assertEqual(pr.status_code, 200, pr.content)
        self.assertEqual(pr.json()['data']['amount'], 20000)
        # user lain tidak bisa melihat / mengubah / menghapus
        self.login('u2@x.com')
        self.assertEqual(self.c.get(f'/api/expenses/{eid}').status_code, 404)
        self.assertEqual(self.c.delete(f'/api/expenses/{eid}').status_code, 404)
        self.assertEqual(self.c.get('/api/expenses').json()['meta']['total'], 0)
        # admin TIDAK melihat pengeluaran user lain; superadmin melihat semua
        self.login('admin@x.com')
        self.assertEqual(self.c.get('/api/expenses').json()['meta']['total'], 0)
        self.assertEqual(self.c.get(f'/api/expenses/{eid}').status_code, 404)
        self.login('super@x.com')
        self.assertEqual(self.c.get('/api/expenses').json()['meta']['total'], 1)
        self.login('u1@x.com')
        self.assertEqual(self.c.delete(f'/api/expenses/{eid}').status_code, 204)

    def test_expense_rejects_foreign_category(self):
        foreign = Category.objects.create(user=self.u2, name='Rahasia')
        self.login('u1@x.com')
        r = self.c.post('/api/expenses', {'title': 'X', 'amount': 1000, 'date': '2026-09-01', 'categoryId': foreign.id}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_expense_validation(self):
        self.login('u1@x.com')
        r = self.c.post('/api/expenses', {'title': '', 'amount': -5, 'date': 'kemarin'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertGreaterEqual(len(r.json()['errors']), 2)

    def test_pagination_filter_sort_summary(self):
        cat = Category.objects.create(user=self.u1, name='Makanan')
        for i in range(25):
            Expense.objects.create(user=self.u1, category=cat if i % 2 == 0 else None, title=f'Item {i}',
                                   amount=1000 * (i + 1), date=f'2026-09-{i + 1:02d}')
        self.login('u1@x.com')
        r = self.c.get('/api/expenses?limit=10&page=3').json()
        self.assertEqual(len(r['data']), 5)
        self.assertEqual(r['meta'], {'page': 3, 'limit': 10, 'total': 25, 'totalPages': 3, 'hasNext': False, 'hasPrev': True})
        self.assertEqual(self.c.get('/api/expenses?limit=500').json()['meta']['limit'], 100)
        self.assertEqual(self.c.get('/api/expenses?q=item 1').json()['meta']['total'], 11)
        self.assertEqual(self.c.get('/api/expenses?minAmount=20000&maxAmount=22000').json()['meta']['total'], 3)
        self.assertEqual(self.c.get(f'/api/expenses?categoryId={cat.id}').json()['meta']['total'], 13)
        self.assertEqual(self.c.get('/api/expenses?from=2026-09-20&to=2026-09-22').json()['meta']['total'], 3)
        self.assertEqual(self.c.get('/api/expenses?sort=-amount').json()['data'][0]['amount'], 25000)
        s = self.c.get('/api/expenses/summary').json()['data']
        self.assertEqual(s['count'], 25)
        self.assertEqual(s['total'], sum(1000 * (i + 1) for i in range(25)))
        self.assertIn('Makanan', s['byCategory'])

    def test_expense_list_uses_constant_queries(self):
        cat = Category.objects.create(user=self.u1, name='M')
        for i in range(15):
            Expense.objects.create(user=self.u1, category=cat, title=f'e{i}', amount=1000, date='2026-09-01')
        self.login('u1@x.com')
        with self.assertNumQueries(3):  # auth user + count + list(JOIN kategori); tidak N+1
            self.c.get('/api/expenses?limit=15')

    def test_bills_pay_filter_overdue(self):
        today = timezone.localdate()
        Bill.objects.create(user=self.u1, name='Listrik', amount=200000, due_date=today - timedelta(days=3))
        Bill.objects.create(user=self.u1, name='Internet', amount=350000, due_date=today + timedelta(days=5))
        self.login('u1@x.com')
        self.assertEqual(self.c.get('/api/bills?status=overdue').json()['meta']['total'], 1)
        self.assertTrue(self.c.get('/api/bills').json()['data'][0]['isOverdue'] is True)
        bid = Bill.objects.get(name='Listrik').id
        self.assertEqual(self.c.post(f'/api/bills/{bid}/pay').status_code, 403)  # user tidak bisa lunas sendiri
        self.login('super@x.com')
        r = self.c.post(f'/api/bills/{bid}/pay').json()['data']
        self.assertEqual(r['status'], 'paid')
        self.assertIsNotNone(r['paidAt'])
        self.assertEqual(self.c.get('/api/bills?status=overdue').json()['meta']['total'], 0)

    def test_users_admin_only(self):
        self.login('u1@x.com')
        self.assertEqual(self.c.get('/api/users').status_code, 403)
        self.login('admin@x.com')
        self.assertEqual(self.c.get('/api/users').json()['meta']['total'], 3)  # superadmin tidak terlihat oleh admin
        self.assertEqual(self.c.delete(f'/api/users/{self.u2.id}').status_code, 403)  # hapus user: superadmin saja
        self.login('super@x.com')
        self.assertEqual(self.c.get('/api/users').json()['meta']['total'], 4)
        self.assertEqual(self.c.delete(f'/api/users/{self.sa.id}').status_code, 400)
        self.assertEqual(self.c.delete(f'/api/users/{self.u2.id}').status_code, 204)
        self.assertEqual(self.c.delete('/api/users/9999').status_code, 404)


class StatsTests(Base):
    def setUp(self):
        super().setUp()
        self.u1, self.u2, self.u3 = mk('u1@x.com'), mk('u2@x.com'), mk('u3@x.com')
        self.admin = mk('admin@x.com', 'admin')
        self.sa = mk('super@x.com', 'superadmin')
        m, h = Category.objects.create(user=self.u1, name='Makanan'), Category.objects.create(user=self.u1, name='Hiburan')
        Expense.objects.create(user=self.u1, category=m, title='a', amount=30000, date='2026-08-10')
        Expense.objects.create(user=self.u1, category=m, title='b', amount=57000, date='2026-09-10')
        Expense.objects.create(user=self.u1, category=h, title='c', amount=100000, date='2026-09-11')
        Expense.objects.create(user=self.u2, title='d', amount=5000, date='2026-09-12')

    def test_expense_stats(self):
        self.login('u1@x.com')
        d = self.c.get('/api/stats/expenses').json()['data']
        self.assertEqual((d['expenseCount'], d['total'], d['min'], d['max']), (3, 187000, 30000, 100000))
        self.assertEqual(d['byCategory'][0], {'category': 'Hiburan', 'total': 100000, 'count': 1})
        self.assertEqual([m['month'] for m in d['monthly']], ['2026-08', '2026-09'])
        self.assertEqual(d['cheapest'][0]['title'], 'a')
        self.assertEqual(d['mostExpensive'][0]['category'], 'Hiburan')

    def test_user_stats_admin(self):
        self.login('u1@x.com')
        self.assertEqual(self.c.get('/api/stats/users').status_code, 403)
        self.login('admin@x.com')
        d = self.c.get('/api/stats/users').json()['data']
        self.assertEqual((d['totalUsers'], d['usersWithExpenses'], d['usersWithoutExpenses']), (3, 2, 1))
        self.assertEqual(d['topUsers'][0]['email'], 'u1@x.com')
        self.assertEqual(d['usersNoExpenses'][0]['email'], 'u3@x.com')

    def test_bill_stats(self):
        Bill.objects.create(user=self.u1, name='x', amount=100, due_date=timezone.localdate() - timedelta(days=1))
        Bill.objects.create(user=self.u1, name='y', amount=50, due_date=timezone.localdate(), status='paid')
        self.login('u1@x.com')
        d = self.c.get('/api/stats/bills').json()['data']
        self.assertEqual(d['overdue']['count'], 1)
        self.assertEqual(d['paid']['total'], 50)


class ImporterAndPageTests(Base):
    def test_import_is_idempotent(self):
        call_command('import_csv', verbosity=0)
        n = (User.objects.count(), Category.objects.count(), Expense.objects.count(), Bill.objects.count())
        self.assertGreater(n[2], 0)
        call_command('import_csv', verbosity=0)
        self.assertEqual(n, (User.objects.count(), Category.objects.count(), Expense.objects.count(), Bill.objects.count()))
        self.assertTrue(User.objects.get(email='admin2@finebank.test').is_superuser)  # superadmin
        staff = User.objects.get(email='staff@finebank.test')
        self.assertEqual((staff.role, staff.is_staff), ('admin', False))
        self.login('najwa@finebank.test')

    def test_seed_demo(self):
        call_command('seed_demo', verbosity=0)
        call_command('seed_demo', verbosity=0)
        self.assertEqual(Expense.objects.filter(user__email='arief@finebank.test').count(), 4)
        self.assertEqual(User.objects.get(email='superadmin@finebank.test').role, 'superadmin')
        self.login('arief@finebank.test')

    def test_pages_docs_health(self):
        for p in ['/', '/statistik', '/pengeluaran', '/tagihan', '/pembayaran', '/impor', '/health', '/api/docs/', '/api/schema/']:
            self.assertEqual(self.c.get(p).status_code, 200, p)
        self.assertIn('Chart', self.c.get('/statistik').content.decode())

    def test_silk_and_admin_need_login(self):
        self.assertIn(self.c.get('/admin/').status_code, (302, 301))
        r = self.c.get('/silk/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/admin/login/', r['Location'])
