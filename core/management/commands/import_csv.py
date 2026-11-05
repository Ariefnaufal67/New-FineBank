"""Import data massal dari CSV (materi 5/6: bulk_create, idempotent)."""
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.contrib.auth.hashers import make_password
from django.utils import timezone

from core.models import Bill, Category, Expense, User


def read(directory, name):
    p = Path(directory) / name
    if not p.exists():
        return []
    with p.open(newline='', encoding='utf-8') as f:
        return [{k.strip(): (v or '').strip() for k, v in row.items()} for row in csv.DictReader(f)]


def num(v):
    try:
        return Decimal(v)
    except (InvalidOperation, TypeError):
        return None


def run_import(directory):
    res = {'users': 0, 'categories': 0, 'expenses': 0, 'bills': 0, 'skipped': 0}

    # 1. users (hash sekali per password unik agar cepat)
    rows = [r for r in read(directory, 'users.csv') if r.get('email') and r.get('password')]
    known = set(User.objects.filter(email__in=[r['email'] for r in rows]).values_list('email', flat=True))
    fresh = [r for r in rows if r['email'] not in known]
    hashes = {}
    new_users = []
    for r in fresh:
        h = hashes.setdefault(r['password'], make_password(r['password']))
        role = r.get('role') if r.get('role') in ('superadmin', 'admin') else 'user'
        # bulk_create tidak memanggil save(): flag staff/superuser diatur di sini (hanya superadmin)
        new_users.append(User(username=r['email'], email=r['email'], name=r['name'], password=h, role=role,
                              is_staff=role == 'superadmin', is_superuser=role == 'superadmin'))
    User.objects.bulk_create(new_users)
    res['users'] = len(new_users)
    id_by_email = dict(User.objects.filter(email__in=[r['email'] for r in rows]).values_list('email', 'id'))
    uids = list(id_by_email.values())

    # 2. categories
    have = set(Category.objects.filter(user_id__in=uids).values_list('user_id', 'name'))
    new_cats = []
    for r in read(directory, 'categories.csv'):
        uid = id_by_email.get(r.get('userEmail'))
        if not uid:
            res['skipped'] += 1
            continue
        if (uid, r['name']) not in have:
            have.add((uid, r['name']))
            new_cats.append(Category(user_id=uid, name=r['name']))
    Category.objects.bulk_create(new_cats)
    res['categories'] = len(new_cats)
    cat_id = {(u, n): i for i, u, n in Category.objects.filter(user_id__in=uids).values_list('id', 'user_id', 'name')}

    # 3. expenses
    have = {(u, t, d, a) for u, t, d, a in Expense.objects.filter(user_id__in=uids).values_list('user_id', 'title', 'date', 'amount')}
    new_exp = []
    for r in read(directory, 'expenses.csv'):
        uid, amount = id_by_email.get(r.get('userEmail')), num(r.get('amount'))
        if not uid or not r.get('title') or amount is None:
            res['skipped'] += 1
            continue
        date = datetime.strptime(r['date'], '%Y-%m-%d').date()
        key = (uid, r['title'], date, amount)
        if key in have:
            continue
        have.add(key)
        new_exp.append(Expense(user_id=uid, category_id=cat_id.get((uid, r.get('category'))), title=r['title'],
                               amount=amount, date=date, note=r.get('note') or None))
    Expense.objects.bulk_create(new_exp)
    res['expenses'] = len(new_exp)

    # 4. bills
    have = {(u, n, d) for u, n, d in Bill.objects.filter(user_id__in=uids).values_list('user_id', 'name', 'due_date')}
    new_bills = []
    for r in read(directory, 'bills.csv'):
        uid, amount = id_by_email.get(r.get('userEmail')), num(r.get('amount'))
        if not uid or not r.get('name') or amount is None:
            res['skipped'] += 1
            continue
        due = datetime.strptime(r['dueDate'], '%Y-%m-%d').date()
        if (uid, r['name'], due) in have:
            continue
        have.add((uid, r['name'], due))
        paid = r.get('status') == 'paid'
        paid_at = timezone.make_aware(datetime.combine(due, datetime.min.time())) if paid else None
        new_bills.append(Bill(user_id=uid, name=r['name'], amount=amount, due_date=due,
                              status='paid' if paid else 'unpaid', paid_at=paid_at))
    Bill.objects.bulk_create(new_bills)
    res['bills'] = len(new_bills)
    return res


class Command(BaseCommand):
    help = 'Import users/categories/expenses/bills dari folder csv_data (idempotent, bulk_create).'

    def add_arguments(self, parser):
        parser.add_argument('--dir', default=str(settings.BASE_DIR / 'csv_data'))

    def handle(self, *args, **opts):
        r = run_import(opts['dir'])
        self.stdout.write(self.style.SUCCESS(
            f"Import selesai: {r['users']} user, {r['categories']} kategori, {r['expenses']} pengeluaran, "
            f"{r['bills']} tagihan baru ({r['skipped']} baris dilewati)"))
