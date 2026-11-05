"""Seeder akun & data demo (idempotent)."""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Bill, Category, Expense, User


class Command(BaseCommand):
    help = 'Isi akun demo: admin@finebank.test dan arief@finebank.test (password: password123).'

    def handle(self, *args, **opts):
        d = lambda n: timezone.localdate() + timedelta(days=n)  # noqa: E731
        superadmin, _ = User.objects.get_or_create(email='superadmin@finebank.test', defaults={
            'username': 'superadmin@finebank.test', 'name': 'Superadmin FineBank', 'role': 'superadmin'})
        admin, _ = User.objects.get_or_create(email='admin@finebank.test', defaults={
            'username': 'admin@finebank.test', 'name': 'Admin FineBank', 'role': 'admin'})
        user, created = User.objects.get_or_create(email='arief@finebank.test', defaults={
            'username': 'arief@finebank.test', 'name': 'Arief', 'role': 'user'})
        for u in (superadmin, admin, user):
            if not u.has_usable_password() or u.password == '':
                u.set_password('password123')
                u.save()
        if created or not user.expenses.exists():
            u = user
            u.set_password('password123')
            u.save()
            food, _ = Category.objects.get_or_create(user=u, name='Food')
            trans, _ = Category.objects.get_or_create(user=u, name='Transport')
            fun, _ = Category.objects.get_or_create(user=u, name='Entertainment')
            Expense.objects.bulk_create([
                Expense(user=u, category=food, title='Makan siang', amount=25000, date=d(-1)),
                Expense(user=u, category=food, title='Kopi', amount=18000, date=d(-2)),
                Expense(user=u, category=trans, title='Bensin', amount=50000, date=d(-3)),
                Expense(user=u, category=fun, title='Nonton film', amount=45000, date=d(-5)),
            ])
            Bill.objects.bulk_create([
                Bill(user=u, name='Internet', amount=350000, due_date=d(5)),
                Bill(user=u, name='Listrik', amount=200000, due_date=d(-3)),
                Bill(user=u, name='Kos', amount=800000, due_date=d(-10), status='paid', paid_at=timezone.now()),
            ])
        self.stdout.write(self.style.SUCCESS('Seed selesai. Login: superadmin@ / admin@ / arief@finebank.test, password123'))
