"""Logika impor pengeluaran untuk satu user (dipakai endpoint admin)."""
import csv
import io
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction

from .models import Category, Expense

MAX_ROWS = 1000


class ImportError_(Exception):
    pass


def parse_csv_bytes(raw):
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ImportError_('File harus berformat UTF-8')
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or not {'title', 'amount', 'date'} <= {h.strip() for h in reader.fieldnames}:
        raise ImportError_('Header CSV wajib memuat kolom: title, amount, date (opsional: category, note)')
    return [{(k or '').strip(): (v or '').strip() for k, v in row.items()} for row in reader]


def import_expenses(target_user, rows):
    """Impor baris ke target_user. Baris valid disimpan (bulk_create), baris salah dilaporkan.
    Idempotent: baris yang sama (judul+tanggal+jumlah) dilewati."""
    if len(rows) > MAX_ROWS:
        raise ImportError_(f'Maksimal {MAX_ROWS} baris per impor')
    errors, clean = [], []
    for i, r in enumerate(rows, start=2):  # baris 1 = header
        title = (r.get('title') or '').strip()
        try:
            amount = Decimal(str(r.get('amount')).strip())
            if amount <= 0 or amount > Decimal(10 ** 12):
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            errors.append({'row': i, 'message': 'amount harus angka positif'})
            continue
        try:
            date = datetime.strptime(str(r.get('date')).strip(), '%Y-%m-%d').date()
        except ValueError:
            errors.append({'row': i, 'message': 'date harus berformat YYYY-MM-DD'})
            continue
        if not title or len(title) > 120:
            errors.append({'row': i, 'message': 'title wajib diisi (maks 120 karakter)'})
            continue
        clean.append({'title': title, 'amount': amount, 'date': date,
                      'category': (r.get('category') or '').strip()[:60], 'note': (r.get('note') or '').strip() or None})

    with transaction.atomic():
        have = set(Expense.objects.filter(user=target_user).values_list('title', 'date', 'amount'))
        names = {c['category'] for c in clean if c['category']}
        cats = {c.name: c for c in Category.objects.filter(user=target_user, name__in=names)}
        for n in names - set(cats):
            cats[n] = Category.objects.create(user=target_user, name=n)
        new, dup = [], 0
        for c in clean:
            key = (c['title'], c['date'], c['amount'])
            if key in have:
                dup += 1
                continue
            have.add(key)
            new.append(Expense(user=target_user, category=cats.get(c['category']), title=c['title'],
                               amount=c['amount'], date=c['date'], note=c['note']))
        Expense.objects.bulk_create(new)
    return {'created': len(new), 'duplicates': dup, 'failed': len(errors), 'errors': errors[:20]}
