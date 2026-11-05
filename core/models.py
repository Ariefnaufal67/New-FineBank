from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    """Pengguna FineBank. Login memakai email; role user < admin < superadmin."""

    class Role(models.TextChoices):
        SUPERADMIN = 'superadmin', 'Superadmin'
        ADMIN = 'admin', 'Admin'
        USER = 'user', 'User'

    name = models.CharField('nama', max_length=100)
    email = models.EmailField('email', max_length=150, unique=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.USER)

    REQUIRED_FIELDS = ['email', 'name']

    def save(self, *args, **kwargs):
        if self._state.adding and self.is_superuser:  # createsuperuser -> superadmin
            self.role = self.Role.SUPERADMIN
        # Hanya superadmin yang boleh masuk Django Admin (/admin) dan Silk (/silk)
        self.is_superuser = self.is_staff = self.role == self.Role.SUPERADMIN
        super().save(*args, **kwargs)

    @property
    def is_superadmin(self):
        return self.role == self.Role.SUPERADMIN

    @property
    def is_admin_or_above(self):
        return self.role in (self.Role.ADMIN, self.Role.SUPERADMIN)

    def __str__(self):
        return f'{self.name} <{self.email}>'


class Category(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='categories')
    name = models.CharField('nama', max_length=60)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Kategori'
        verbose_name_plural = 'Kategori'
        ordering = ['name']
        constraints = [models.UniqueConstraint(fields=['user', 'name'], name='uniq_category_user_name')]

    def __str__(self):
        return self.name


class Expense(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='expenses')
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL, related_name='expenses')
    title = models.CharField('judul', max_length=120)
    amount = models.DecimalField('jumlah', max_digits=14, decimal_places=2)
    date = models.DateField('tanggal')
    note = models.TextField('catatan', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Pengeluaran'
        verbose_name_plural = 'Pengeluaran'
        ordering = ['-date', '-id']
        indexes = [models.Index(fields=['user', 'date'], name='exp_user_date_idx'),
                   models.Index(fields=['category'], name='exp_category_idx')]

    def __str__(self):
        return f'{self.title} ({self.amount})'


class Bill(models.Model):
    class Status(models.TextChoices):
        UNPAID = 'unpaid', 'Belum dibayar'
        PAID = 'paid', 'Lunas'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bills')
    name = models.CharField('nama', max_length=120)
    amount = models.DecimalField('jumlah', max_digits=14, decimal_places=2)
    due_date = models.DateField('jatuh tempo')
    status = models.CharField(max_length=6, choices=Status.choices, default=Status.UNPAID)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Tagihan'
        verbose_name_plural = 'Tagihan'
        ordering = ['due_date', 'id']
        indexes = [models.Index(fields=['user', 'due_date'], name='bill_user_due_idx'),
                   models.Index(fields=['status'], name='bill_status_idx')]

    @property
    def is_overdue(self):
        # "overdue" tidak disimpan: dihitung dari status unpaid + jatuh tempo lewat
        return self.status == self.Status.UNPAID and self.due_date < timezone.localdate()

    def __str__(self):
        return self.name


class PaymentProof(models.Model):
    """Bukti pembayaran yang dikirim user; tagihan baru lunas setelah admin menyetujui."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Menunggu verifikasi'
        APPROVED = 'approved', 'Disetujui'
        REJECTED = 'rejected', 'Ditolak'

    bill = models.ForeignKey(Bill, on_delete=models.CASCADE, related_name='proofs')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='proofs')
    note = models.TextField('keterangan')
    proof_url = models.URLField('tautan bukti', max_length=500, blank=True, default='')
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name='reviewed_proofs')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Bukti pembayaran'
        verbose_name_plural = 'Bukti pembayaran'
        ordering = ['-id']
        indexes = [models.Index(fields=['status'], name='proof_status_idx')]

    def __str__(self):
        return f'Bukti {self.bill_id} ({self.status})'
