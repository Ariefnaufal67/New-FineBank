from rest_framework import serializers
from decimal import Decimal

from .models import Bill, Category, Expense, PaymentProof, User

AMOUNT = dict(max_digits=14, decimal_places=2, coerce_to_string=False, min_value=Decimal("0.01"), max_value=Decimal(10 ** 12))


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'name', 'email', 'role']


class RegisterSerializer(serializers.Serializer):
    name = serializers.CharField(min_length=2, max_length=100)
    email = serializers.EmailField(max_length=150)
    password = serializers.CharField(min_length=8, max_length=72, write_only=True)

    def validate_email(self, value):
        return value.strip().lower()


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()

    def validate_email(self, value):
        return value.strip().lower()


class CategorySerializer(serializers.ModelSerializer):
    userId = serializers.IntegerField(source='user_id', read_only=True)
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)
    updatedAt = serializers.DateTimeField(source='updated_at', read_only=True)
    name = serializers.CharField(max_length=60)

    class Meta:
        model = Category
        fields = ['id', 'name', 'userId', 'createdAt', 'updatedAt']


class CategoryBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name']


class ExpenseSerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(**AMOUNT)
    userId = serializers.IntegerField(source='user_id', read_only=True)
    categoryId = serializers.PrimaryKeyRelatedField(source='category', queryset=Category.objects.all(),
                                                    allow_null=True, required=False)
    category = CategoryBriefSerializer(read_only=True)
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)
    updatedAt = serializers.DateTimeField(source='updated_at', read_only=True)
    note = serializers.CharField(max_length=1000, required=False, allow_null=True, allow_blank=True)

    class Meta:
        model = Expense
        fields = ['id', 'title', 'amount', 'date', 'note', 'userId', 'categoryId', 'category', 'createdAt', 'updatedAt']

    def validate_categoryId(self, value):
        # kategori harus milik pengguna yang sedang login
        if value is not None and value.user_id != self.context['request'].user.id:
            raise serializers.ValidationError('categoryId tidak valid')
        return value

    def to_internal_value(self, data):
        # kategori yang tidak ada -> pesan yang sama dengan kategori milik orang lain
        try:
            return super().to_internal_value(data)
        except serializers.ValidationError as e:
            if 'categoryId' in e.detail:
                e.detail['categoryId'] = ['categoryId tidak valid']
            raise


class BillSerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(**AMOUNT)
    userId = serializers.IntegerField(source='user_id', read_only=True)
    dueDate = serializers.DateField(source='due_date')
    paidAt = serializers.DateTimeField(source='paid_at', read_only=True)
    isOverdue = serializers.BooleanField(source='is_overdue', read_only=True)
    proofStatus = serializers.SerializerMethodField()
    ownerName = serializers.CharField(source='user.name', read_only=True)
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)
    updatedAt = serializers.DateTimeField(source='updated_at', read_only=True)

    class Meta:
        model = Bill
        fields = ['id', 'name', 'amount', 'dueDate', 'status', 'paidAt', 'userId', 'isOverdue', 'proofStatus', 'ownerName',
                  'createdAt', 'updatedAt']

    def get_proofStatus(self, obj):
        # status bukti terbaru (pending/approved/rejected) atau null; proofs di-prefetch di view
        proofs = obj.proofs.all()
        return proofs[0].status if proofs else None


class PaymentProofSerializer(serializers.ModelSerializer):
    billId = serializers.IntegerField(source='bill_id', read_only=True)
    bill = serializers.SerializerMethodField()
    user = serializers.SerializerMethodField()
    proofUrl = serializers.CharField(source='proof_url', read_only=True)
    reviewedBy = serializers.SerializerMethodField()
    reviewedAt = serializers.DateTimeField(source='reviewed_at', read_only=True)
    reviewNote = serializers.CharField(source='review_note', read_only=True)
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)

    class Meta:
        model = PaymentProof
        fields = ['id', 'billId', 'bill', 'user', 'note', 'proofUrl', 'status', 'reviewedBy', 'reviewedAt',
                  'reviewNote', 'createdAt']

    def get_bill(self, o):
        return {'id': o.bill_id, 'name': o.bill.name, 'amount': float(o.bill.amount), 'dueDate': o.bill.due_date.isoformat(),
                'status': o.bill.status}

    def get_user(self, o):
        return {'id': o.user_id, 'name': o.user.name, 'email': o.user.email}

    def get_reviewedBy(self, o):
        return o.reviewed_by.name if o.reviewed_by_id else None


class ProofCreateSerializer(serializers.Serializer):
    note = serializers.CharField(min_length=3, max_length=500, help_text='Keterangan pembayaran (bank, tanggal, nominal)')
    proofUrl = serializers.URLField(max_length=500, required=False, allow_blank=True)


class RoleUpdateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=['user', 'admin', 'superadmin'])


class ExpenseQuerySerializer(serializers.Serializer):
    q = serializers.CharField(max_length=100, required=False)
    categoryId = serializers.IntegerField(min_value=1, required=False)
    minAmount = serializers.DecimalField(max_digits=16, decimal_places=2, min_value=0, required=False)
    maxAmount = serializers.DecimalField(max_digits=16, decimal_places=2, min_value=0, required=False)
    sort = serializers.CharField(required=False)


class BillQuerySerializer(serializers.Serializer):
    q = serializers.CharField(max_length=100, required=False)
    status = serializers.ChoiceField(choices=['unpaid', 'paid', 'overdue'], required=False)
    sort = serializers.CharField(required=False)


# 'from' adalah kata kunci Python, jadi field rentang tanggal ditambahkan secara dinamis
for _cls in (ExpenseQuerySerializer, BillQuerySerializer):
    _cls._declared_fields['from'] = serializers.DateField(required=False)
    _cls._declared_fields['to'] = serializers.DateField(required=False)
