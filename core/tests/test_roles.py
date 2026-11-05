from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Bill, Expense, PaymentProof, User


def mk(email, role='user'):
    return User.objects.create_user(username=email, email=email, name=email.split('@')[0], password='password123', role=role)


class RoleBase(TestCase):
    def setUp(self):
        cache.clear()
        self.c = APIClient()
        self.u1, self.u2 = mk('u1@x.com'), mk('u2@x.com')
        self.admin, self.sa = mk('admin@x.com', 'admin'), mk('super@x.com', 'superadmin')
        self.bill = Bill.objects.create(user=self.u1, name='Listrik', amount=200000,
                                        due_date=timezone.localdate() - timedelta(days=2))

    def login(self, email):
        r = self.c.post('/api/auth/login', {'email': email, 'password': 'password123'}, format='json')
        self.c.credentials(HTTP_AUTHORIZATION='Bearer ' + r.json()['data']['token'])


class RoleFlagsTests(RoleBase):
    def test_only_superadmin_is_staff(self):
        self.assertEqual([(u.role, u.is_staff, u.is_superuser) for u in (self.u1, self.admin, self.sa)],
                         [('user', False, False), ('admin', False, False), ('superadmin', True, True)])

    def test_createsuperuser_becomes_superadmin(self):
        u = User.objects.create_superuser(username='s@x.com', email='s@x.com', password='x', name='S')
        self.assertEqual(u.role, 'superadmin')

    def test_demote_removes_staff(self):
        self.sa.role = 'admin'
        self.sa.save()
        self.assertEqual((self.sa.is_staff, self.sa.is_superuser), (False, False))


class PaymentProofFlowTests(RoleBase):
    def test_user_cannot_mark_paid_or_submit_proof(self):
        self.login('u1@x.com')
        self.assertEqual(self.c.put(f'/api/bills/{self.bill.id}', {'status': 'paid'}, format='json').status_code, 403)
        r = self.c.post('/api/bills', {'name': 'Air', 'amount': 1000, 'dueDate': '2026-12-01', 'status': 'paid'}, format='json')
        self.assertEqual(r.status_code, 403)
        # user tidak bisa memasukkan bukti: hanya admin
        r = self.c.post(f'/api/bills/{self.bill.id}/proof', {'note': 'Sudah transfer BCA'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(PaymentProof.objects.count(), 0)
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, 'unpaid')

    def test_admin_records_payment_and_user_only_views(self):
        self.login('admin@x.com')
        r = self.c.post(f'/api/bills/{self.bill.id}/proof', {'note': 'Transfer BCA 20 Okt', 'proofUrl': 'https://x.com/bukti.jpg'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()['data']
        self.assertEqual((d['status'], d['reviewedBy'], d['user']['email']), ('approved', 'admin', 'u1@x.com'))
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, 'paid')
        self.assertIsNotNone(self.bill.paid_at)
        self.assertEqual(self.c.post(f'/api/bills/{self.bill.id}/proof', {'note': 'dobel catat'}, format='json').status_code, 409)
        # user melihat buktinya, tidak bisa mengubah/menghapus
        self.login('u1@x.com')
        listing = self.c.get('/api/payments').json()
        self.assertEqual(listing['meta']['total'], 1)
        self.assertEqual(listing['data'][0]['proofUrl'], 'https://x.com/bukti.jpg')
        self.assertEqual(self.c.get('/api/bills').json()['data'][0]['proofStatus'], 'approved')
        self.assertEqual(self.c.post(f"/api/payments/{d['id']}/approve").status_code, 404)
        self.assertEqual(self.c.delete(f"/api/payments/{d['id']}").status_code, 405)
        # user lain tidak melihat
        self.login('u2@x.com')
        self.assertEqual(self.c.get('/api/payments').json()['meta']['total'], 0)

    def test_proof_validation(self):
        self.login('admin@x.com')
        self.assertEqual(self.c.post(f'/api/bills/{self.bill.id}/proof', {'note': 'x'}, format='json').status_code, 400)
        self.assertEqual(self.c.post(f'/api/bills/{self.bill.id}/proof', {'note': 'valid note', 'proofUrl': 'bukan-url'}, format='json').status_code, 400)
        self.assertEqual(self.c.post('/api/bills/99999/proof', {'note': 'valid note'}, format='json').status_code, 404)

    def test_admin_cannot_record_own_bill_but_superadmin_can(self):
        b = Bill.objects.create(user=self.admin, name='Kos', amount=1, due_date='2026-12-01')
        self.login('admin@x.com')
        self.assertEqual(self.c.post(f'/api/bills/{b.id}/proof', {'note': 'saya bayar sendiri'}, format='json').status_code, 403)
        self.login('super@x.com')
        self.assertEqual(self.c.post(f'/api/bills/{b.id}/proof', {'note': 'dicatat superadmin'}, format='json').status_code, 201)

    def test_admin_reads_all_bills_but_cannot_edit_or_delete_them(self):
        self.login('admin@x.com')
        self.assertEqual(self.c.get('/api/bills').json()['meta']['total'], 1)
        self.assertEqual(self.c.put(f'/api/bills/{self.bill.id}', {'name': 'x'}, format='json').status_code, 404)
        self.assertEqual(self.c.delete(f'/api/bills/{self.bill.id}').status_code, 404)
        self.assertEqual(self.c.post(f'/api/bills/{self.bill.id}/pay').status_code, 403)

    def test_bill_list_has_constant_queries(self):
        for i in range(8):
            b = Bill.objects.create(user=self.u1, name=f'b{i}', amount=1, due_date='2026-12-01')
            PaymentProof.objects.create(bill=b, user=self.u1, note='x')
        self.login('u1@x.com')
        with self.assertNumQueries(4):  # user + count + bills(JOIN user) + prefetch proofs (tanpa N+1)
            self.c.get('/api/bills?limit=20')


class AdminImportTests(RoleBase):
    CSV = ('title,amount,date,category,note\n'
           'Nasi goreng,18000,2026-09-03,Makanan,\n'
           'Kopi,22000,2026-09-05,Makanan,dekat kampus\n'
           'Rusak,abc,2026-09-06,,\n'
           'Salah tanggal,5000,06-09-2026,,\n')

    def _file(self, text):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile('data.csv', text.encode(), content_type='text/csv')

    def test_admin_imports_for_specific_user_with_row_errors(self):
        self.login('admin@x.com')
        r = self.c.post(f'/api/users/{self.u1.id}/import-expenses', {'file': self._file(self.CSV)}, format='multipart')
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()['data']
        self.assertEqual((d['created'], d['failed'], d['duplicates']), (2, 2, 0))
        self.assertEqual({e['row'] for e in d['errors']}, {4, 5})
        self.assertEqual(Expense.objects.filter(user=self.u1).count(), 2)
        self.assertEqual(Expense.objects.filter(user=self.u2).count(), 0)
        self.assertEqual(self.u1.categories.filter(name='Makanan').count(), 1)
        # idempotent
        r2 = self.c.post(f'/api/users/{self.u1.id}/import-expenses', {'file': self._file(self.CSV)}, format='multipart')
        self.assertEqual(r2.json()['data']['duplicates'], 2)
        self.assertEqual(Expense.objects.filter(user=self.u1).count(), 2)

    def test_import_json_and_validation(self):
        self.login('admin@x.com')
        r = self.c.post(f'/api/users/{self.u2.id}/import-expenses',
                        {'expenses': [{'title': 'Ojek', 'amount': 15000, 'date': '2026-10-01'}]}, format='json')
        self.assertEqual(r.json()['data']['created'], 1)
        bad = self.c.post(f'/api/users/{self.u2.id}/import-expenses', {}, format='json')
        self.assertEqual(bad.status_code, 400)
        hdr = self.c.post(f'/api/users/{self.u2.id}/import-expenses', {'file': self._file('a,b\n1,2\n')}, format='multipart')
        self.assertEqual(hdr.status_code, 400)

    def test_user_cannot_import_and_admin_cannot_target_admin(self):
        self.login('u1@x.com')
        self.assertEqual(self.c.post(f'/api/users/{self.u2.id}/import-expenses', {'expenses': []}, format='json').status_code, 403)
        self.login('admin@x.com')
        other_admin = mk('admin2@x.com', 'admin')
        self.assertEqual(self.c.post(f'/api/users/{other_admin.id}/import-expenses', {'expenses': []}, format='json').status_code, 403)
        # superadmin tidak terlihat oleh admin -> 404
        self.assertEqual(self.c.post(f'/api/users/{self.sa.id}/import-expenses', {'expenses': []}, format='json').status_code, 404)


class RoleManagementTests(RoleBase):
    def test_superadmin_changes_roles(self):
        self.login('super@x.com')
        r = self.c.patch(f'/api/users/{self.u1.id}', {'role': 'admin'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.u1.refresh_from_db()
        self.assertEqual(self.u1.role, 'admin')
        self.assertEqual(self.c.patch(f'/api/users/{self.sa.id}', {'role': 'user'}, format='json').status_code, 400)  # akun sendiri
        self.assertEqual(self.c.patch(f'/api/users/{self.u2.id}', {'role': 'dewa'}, format='json').status_code, 400)

    def test_admin_and_user_cannot_change_roles(self):
        for email in ('admin@x.com', 'u1@x.com'):
            self.login(email)
            self.assertEqual(self.c.patch(f'/api/users/{self.u2.id}', {'role': 'admin'}, format='json').status_code, 403)

    def test_django_admin_and_silk_only_for_superadmin(self):
        from django.test import Client
        for email, ok in (('admin@x.com', False), ('super@x.com', True)):
            cl = Client()
            cl.login(username=email, password='password123')
            self.assertEqual(cl.get('/admin/').status_code, 200 if ok else 302, email)
