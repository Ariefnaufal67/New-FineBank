"""API FineBank: auth, kategori, pengeluaran, tagihan, user (admin), statistik."""
from datetime import timedelta  # noqa: F401
from decimal import Decimal

from django.contrib.auth.hashers import check_password
from django.db.models import Avg, Count, Max, Min, Prefetch, Sum
from django.db.models.functions import Coalesce, TruncMonth
from django.db import transaction
from django.http import Http404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.exceptions import AuthenticationFailed, NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from .auth import sign_token
from .exceptions import Conflict
from .models import Bill, Category, Expense, PaymentProof, User
from .serializers import (BillQuerySerializer, BillSerializer, CategorySerializer, ExpenseQuerySerializer,
                          ExpenseSerializer, LoginSerializer, PaymentProofSerializer, ProofCreateSerializer,
                          RegisterSerializer, RoleUpdateSerializer, UserSerializer)
from .services import ImportError_, import_expenses, parse_csv_bytes
from .throttles import AuthThrottle


class IsAdminRole(BasePermission):
    """admin dan superadmin."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_admin_or_above)


class IsSuperAdmin(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superadmin)


def scoped(qs, user):
    """Pengeluaran/kategori: hanya superadmin yang melihat semua; user & admin hanya miliknya."""
    return qs if user.is_superadmin else qs.filter(user=user)


def bill_scope(qs, user):
    """Tagihan: admin & superadmin melihat semua (admin hanya membaca + verifikasi bukti)."""
    return qs if user.is_admin_or_above else qs.filter(user=user)


def parse_sort(value, allowed, fallback):
    """?sort=-amount (desc) atau ?sort=date (asc); kolom di luar daftar diabaikan."""
    if not value:
        return fallback
    desc = value.startswith('-')
    field = value[1:] if desc else value
    if field not in allowed:
        return fallback
    col = allowed[field]
    return [('-' if desc else '') + col, 'id']


def validated_query(serializer_cls, request):
    s = serializer_cls(data=request.query_params)
    s.is_valid(raise_exception=True)
    return s.validated_data


class ScopedViewSet(viewsets.GenericViewSet):
    not_found_message = 'Data tidak ditemukan'

    def get_object(self):
        try:
            return super().get_object()
        except Http404:
            raise NotFound(self.not_found_message)

    def get_serializer(self, *args, **kwargs):
        if self.action == 'update':
            kwargs['partial'] = True  # PUT bersifat parsial (sama dengan versi Node)
        return super().get_serializer(*args, **kwargs)


# ---------------- Auth ----------------
class RegisterView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [AuthThrottle]

    @extend_schema(request=RegisterSerializer, responses={201: UserSerializer}, tags=['Auth'])
    def post(self, request):
        s = RegisterSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        if User.objects.filter(email=d['email']).exists():
            raise Conflict('Email sudah terdaftar')
        user = User.objects.create_user(username=d['email'], email=d['email'], name=d['name'], password=d['password'])
        return Response({'success': True, 'data': {'user': UserSerializer(user).data, 'token': sign_token(user)}},
                        status=status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [AuthThrottle]

    @extend_schema(request=LoginSerializer, responses={200: UserSerializer}, tags=['Auth'])
    def post(self, request):
        s = LoginSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        user = User.objects.filter(email=d['email'], is_active=True).first()
        # check_password selalu dijalankan agar waktu respons tidak membocorkan keberadaan email
        ok = check_password(d['password'], user.password if user else 'pbkdf2_sha256$1$x$x')
        if not user or not ok:
            raise AuthenticationFailed('Email atau password salah')
        return Response({'success': True, 'data': {'user': UserSerializer(user).data, 'token': sign_token(user)}})


class MeView(APIView):
    @extend_schema(responses={200: UserSerializer}, tags=['Auth'])
    def get(self, request):
        return Response(UserSerializer(request.user).data)


# ---------------- Kategori ----------------
@extend_schema(tags=['Categories'])
class CategoryViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin,
                      mixins.DestroyModelMixin, ScopedViewSet):
    serializer_class = CategorySerializer
    not_found_message = 'Kategori tidak ditemukan'
    pagination_class = None  # daftar kategori kecil: dikembalikan utuh

    def get_queryset(self):
        return Category.objects.filter(user=self.request.user).order_by('name')

    def _check_duplicate(self, name, exclude_id=None):
        qs = Category.objects.filter(user=self.request.user, name=name)
        if exclude_id:
            qs = qs.exclude(pk=exclude_id)
        if qs.exists():
            raise Conflict('Kategori sudah ada')

    def perform_create(self, serializer):
        self._check_duplicate(serializer.validated_data['name'])
        serializer.save(user=self.request.user)

    def perform_update(self, serializer):
        self._check_duplicate(serializer.validated_data.get('name', serializer.instance.name), serializer.instance.pk)
        serializer.save()


# ---------------- Pengeluaran ----------------
EXPENSE_SORT = {'date': 'date', 'amount': 'amount', 'title': 'title', 'createdAt': 'created_at'}


@extend_schema(tags=['Expenses'])
class ExpenseViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.RetrieveModelMixin,
                     mixins.UpdateModelMixin, mixins.DestroyModelMixin, ScopedViewSet):
    serializer_class = ExpenseSerializer
    not_found_message = 'Expense tidak ditemukan'

    def get_queryset(self):
        # select_related: kategori diambil dalam satu JOIN (menghindari N+1)
        qs = scoped(Expense.objects.select_related('category'), self.request.user)
        if self.action != 'list':
            return qs
        f = validated_query(ExpenseQuerySerializer, self.request)
        if f.get('q'):
            qs = qs.filter(title__icontains=f['q'])
        if f.get('categoryId'):
            qs = qs.filter(category_id=f['categoryId'])
        if f.get('minAmount') is not None:
            qs = qs.filter(amount__gte=f['minAmount'])
        if f.get('maxAmount') is not None:
            qs = qs.filter(amount__lte=f['maxAmount'])
        if f.get('from'):
            qs = qs.filter(date__gte=f['from'])
        if f.get('to'):
            qs = qs.filter(date__lte=f['to'])
        return qs.order_by(*parse_sort(f.get('sort'), EXPENSE_SORT, ['-date', '-id']))

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @extend_schema(summary='Total & ringkasan per kategori')
    @action(detail=False, methods=['get'], pagination_class=None)
    def summary(self, request):
        # Agregasi di database (GROUP BY), bukan memuat semua baris lalu menjumlah di Python
        qs = scoped(Expense.objects.all(), request.user)
        groups = qs.values('category__name').annotate(total=Sum('amount'), n=Count('id'))
        by_category, total, count = {}, Decimal(0), 0
        for g in groups:
            key = g['category__name'] or 'Tanpa kategori'
            by_category[key] = by_category.get(key, 0) + float(g['total'])
            total += g['total']
            count += g['n']
        return Response({'total': float(total), 'count': count, 'byCategory': by_category})


# ---------------- Tagihan ----------------
BILL_SORT = {'dueDate': 'due_date', 'amount': 'amount', 'name': 'name', 'createdAt': 'created_at'}


@extend_schema(tags=['Bills'])
class BillViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.RetrieveModelMixin,
                  mixins.UpdateModelMixin, mixins.DestroyModelMixin, ScopedViewSet):
    serializer_class = BillSerializer
    not_found_message = 'Bill tidak ditemukan'

    def get_queryset(self):
        user = self.request.user
        base = Bill.objects.select_related('user').prefetch_related(Prefetch('proofs', queryset=PaymentProof.objects.order_by('-id')))
        # admin hanya boleh MEMBACA tagihan user lain; ubah/hapus/kirim bukti hanya untuk tagihan sendiri
        if user.role == 'admin' and self.action not in ('list', 'retrieve', 'proof'):
            qs = base.filter(user=user)
        else:
            qs = bill_scope(base, user)
        if self.action != 'list':
            return qs
        f = validated_query(BillQuerySerializer, self.request)
        if f.get('q'):
            qs = qs.filter(name__icontains=f['q'])
        if f.get('status') == 'overdue':
            qs = qs.filter(status='unpaid', due_date__lt=timezone.localdate())
        elif f.get('status'):
            qs = qs.filter(status=f['status'])
        if f.get('from'):
            qs = qs.filter(due_date__gte=f['from'])
        if f.get('to'):
            qs = qs.filter(due_date__lte=f['to'])
        return qs.order_by(*parse_sort(f.get('sort'), BILL_SORT, ['due_date', 'id']))

    def _guard_status(self, new_status, current='unpaid'):
        if new_status is not None and new_status != current and not self.request.user.is_superadmin:
            raise PermissionDenied('Status lunas hanya lewat verifikasi bukti pembayaran oleh admin')

    def perform_create(self, serializer):
        self._guard_status(self.request.data.get('status'))
        serializer.save(user=self.request.user)

    def perform_update(self, serializer):
        new_status = self.request.data.get('status')
        self._guard_status(new_status, serializer.instance.status)
        extra = {}
        if new_status == 'paid' and serializer.instance.status != 'paid':
            extra['paid_at'] = timezone.now()
        elif new_status == 'unpaid':
            extra['paid_at'] = None
        serializer.save(**extra)

    @extend_schema(summary='Tandai lunas langsung (khusus superadmin)', request=None)
    @action(detail=True, methods=['post'], permission_classes=[IsSuperAdmin])
    def pay(self, request, pk=None):
        bill = self.get_object()
        if bill.status != 'paid':
            bill.status, bill.paid_at = 'paid', timezone.now()
            bill.save(update_fields=['status', 'paid_at', 'updated_at'])
        return Response(BillSerializer(bill).data)

    @extend_schema(summary='Catat pembayaran + bukti (admin): tagihan langsung lunas', request=ProofCreateSerializer,
                   responses={201: PaymentProofSerializer})
    @action(detail=True, methods=['post'], permission_classes=[IsAdminRole])
    def proof(self, request, pk=None):
        """Admin memasukkan bukti pembayaran yang diterima dari user; user hanya melihatnya."""
        bill = self.get_object()
        s = ProofCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        if bill.status == 'paid':
            raise Conflict('Tagihan sudah lunas')
        if bill.user_id == request.user.id and not request.user.is_superadmin:
            raise PermissionDenied('Admin tidak dapat mencatat pembayaran untuk tagihannya sendiri')
        now = timezone.now()
        with transaction.atomic():
            proof = PaymentProof.objects.create(
                bill=bill, user=bill.user, note=s.validated_data['note'], proof_url=s.validated_data.get('proofUrl', ''),
                status='approved', reviewed_by=request.user, reviewed_at=now)
            Bill.objects.filter(pk=bill.pk).update(status='paid', paid_at=now)
        proof = PaymentProof.objects.select_related('bill', 'user', 'reviewed_by').get(pk=proof.pk)
        return Response(PaymentProofSerializer(proof).data, status=status.HTTP_201_CREATED)


# ---------------- Bukti pembayaran (hanya baca) ----------------
@extend_schema(tags=['Payments'])
class PaymentProofViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, ScopedViewSet):
    """user: bukti untuk tagihannya (hanya lihat). admin/superadmin: semua bukti."""
    serializer_class = PaymentProofSerializer
    not_found_message = 'Bukti pembayaran tidak ditemukan'

    def get_queryset(self):
        qs = PaymentProof.objects.select_related('bill', 'user', 'reviewed_by')
        if not self.request.user.is_admin_or_above:
            qs = qs.filter(user=self.request.user)
        return qs.order_by('-id')


# ---------------- Users (admin) ----------------
@extend_schema(tags=['Users (admin)'])
class UserViewSet(mixins.ListModelMixin, mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """admin: lihat user & impor pengeluaran untuk user tertentu. superadmin: ubah role & hapus user."""
    serializer_class = UserSerializer
    permission_classes = [IsAdminRole]

    def get_permissions(self):
        if self.action in ('update', 'partial_update', 'destroy'):
            return [IsSuperAdmin()]
        return super().get_permissions()

    def get_queryset(self):
        qs = User.objects.order_by('id')
        if not self.request.user.is_superadmin:
            qs = qs.exclude(role='superadmin')  # admin tidak melihat akun superadmin
        q, role = self.request.query_params.get('q'), self.request.query_params.get('role')
        if q:
            from django.db.models import Q
            qs = qs.filter(Q(name__icontains=q) | Q(email__icontains=q))
        if role in ('user', 'admin', 'superadmin'):
            qs = qs.filter(role=role)
        return qs

    def get_object(self):
        try:
            return super().get_object()
        except Http404:
            raise NotFound('User tidak ditemukan')

    @extend_schema(request=RoleUpdateSerializer, responses={200: UserSerializer}, summary='Ubah role (superadmin)')
    def update(self, request, *args, **kwargs):
        user = self.get_object()
        s = RoleUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        if user.pk == request.user.pk:
            raise ValidationError({'role': 'Tidak dapat mengubah role akun sendiri'})
        user.role = s.validated_data['role']
        user.save()
        return Response(UserSerializer(user).data)

    def destroy(self, request, *args, **kwargs):
        user = self.get_object()
        if user.pk == request.user.pk:
            raise ValidationError({'detail': 'Tidak dapat menghapus akun sendiri'})
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(summary='Impor pengeluaran untuk user tertentu (CSV `file` atau JSON `expenses`)', request=None)
    @action(detail=True, methods=['post'], url_path='import-expenses',
            parser_classes=[MultiPartParser, FormParser, JSONParser])
    def import_expenses(self, request, pk=None):
        target = self.get_object()
        if target.role != 'user' and not request.user.is_superadmin:
            raise PermissionDenied('Admin hanya dapat mengimpor pengeluaran untuk akun user')
        try:
            if 'file' in request.FILES:
                f = request.FILES['file']
                if f.size > 1024 * 1024:
                    raise ImportError_('Ukuran file maksimal 1 MB')
                rows = parse_csv_bytes(f.read())
            elif isinstance(request.data.get('expenses'), list):
                rows = request.data['expenses']
            else:
                raise ImportError_('Kirim file CSV pada field "file" atau array "expenses"')
            result = import_expenses(target, rows)
        except ImportError_ as e:
            raise ValidationError({'file': str(e)})
        result['user'] = {'id': target.id, 'name': target.name, 'email': target.email}
        return Response(result, status=status.HTTP_201_CREATED if result['created'] else status.HTTP_200_OK)


# ---------------- Statistik (query relasional + agregasi) ----------------
def _brief(e):
    return {'id': e.id, 'title': e.title, 'amount': float(e.amount), 'date': e.date.isoformat(),
            'category': e.category.name if e.category else None}


@extend_schema(tags=['Statistik'], responses={200: dict})
class ExpenseStatsView(APIView):
    """COUNT/SUM/MIN/MAX/AVG, termurah/termahal (JOIN), per kategori (GROUP BY), tren bulanan."""

    def get(self, request):
        qs = scoped(Expense.objects.all(), request.user)
        agg = qs.aggregate(count=Count('id'), total=Sum('amount'), min=Min('amount'), max=Max('amount'), avg=Avg('amount'))
        n = lambda v: float(v) if v is not None else 0  # noqa: E731
        with_cat = qs.select_related('category')
        by_cat = qs.values('category__name').annotate(total=Sum('amount'), count=Count('id')).order_by('-total')[:10]
        monthly = qs.annotate(month=TruncMonth('date')).values('month').annotate(
            total=Sum('amount'), count=Count('id')).order_by('month')
        return Response({
            'expenseCount': agg['count'], 'total': n(agg['total']), 'min': n(agg['min']), 'max': n(agg['max']),
            'avg': round(n(agg['avg']), 2),
            'cheapest': [_brief(e) for e in with_cat.order_by('amount', 'id')[:3]],
            'mostExpensive': [_brief(e) for e in with_cat.order_by('-amount', 'id')[:3]],
            'byCategory': [{'category': r['category__name'] or 'Tanpa kategori', 'total': n(r['total']), 'count': r['count']}
                           for r in by_cat],
            'monthly': [{'month': r['month'].strftime('%Y-%m'), 'total': n(r['total']), 'count': r['count']}
                        for r in list(monthly)[-12:]],
        })


@extend_schema(tags=['Statistik'], responses={200: dict})
class BillStatsView(APIView):
    def get(self, request):
        qs = bill_scope(Bill.objects.all(), request.user)
        groups = {g['status']: g for g in qs.values('status').annotate(count=Count('id'), total=Sum('amount'))}
        pick = lambda s: {'count': groups[s]['count'], 'total': float(groups[s]['total'])} if s in groups else {'count': 0, 'total': 0}  # noqa: E731
        od = qs.filter(status='unpaid', due_date__lt=timezone.localdate()).aggregate(count=Count('id'), total=Sum('amount'))
        return Response({'paid': pick('paid'), 'unpaid': pick('unpaid'),
                         'overdue': {'count': od['count'], 'total': float(od['total'] or 0)}})


@extend_schema(tags=['Statistik'], responses={200: dict})
class UserStatsView(APIView):
    """Khusus admin: LEFT JOIN + GROUP BY (teraktif) dan exclude/isnull (tanpa pengeluaran)."""
    permission_classes = [IsAdminRole]

    def get(self, request):
        users = User.objects.filter(role='user')  # admin & superadmin
        total_users = users.count()
        with_exp = users.filter(expenses__isnull=False).distinct().count()
        total_exp = Expense.objects.filter(user__role='user').count()
        top = users.annotate(expenseCount=Count('expenses'), total=Coalesce(Sum('expenses__amount'), Decimal(0))
                             ).order_by('-expenseCount', 'id')[:5]
        none = users.filter(expenses__isnull=True).order_by('id').values('id', 'name', 'email')[:20]
        return Response({
            'totalUsers': total_users, 'usersWithExpenses': with_exp,
            'usersWithoutExpenses': max(total_users - with_exp, 0),
            'avgExpensesPerUser': round(total_exp / total_users, 2) if total_users else 0,
            'topUsers': [{'id': u.id, 'name': u.name, 'email': u.email, 'expenseCount': u.expenseCount, 'total': float(u.total)}
                         for u in top],
            'usersNoExpenses': list(none),
        })
