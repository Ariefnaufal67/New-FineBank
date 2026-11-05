from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Bill, Category, Expense, PaymentProof, User


@admin.register(User)
class FineBankUserAdmin(UserAdmin):
    list_display = ('email', 'name', 'role', 'is_staff', 'date_joined')
    list_filter = ('role', 'is_staff', 'is_active')
    search_fields = ('email', 'name')
    ordering = ('id',)
    fieldsets = UserAdmin.fieldsets + (('FineBank', {'fields': ('name', 'role')}),)
    add_fieldsets = UserAdmin.add_fieldsets + (('FineBank', {'fields': ('email', 'name', 'role')}),)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'created_at')
    search_fields = ('name', 'user__email')
    list_select_related = ('user',)


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('title', 'amount', 'date', 'category', 'user')
    list_filter = ('category', 'date')
    search_fields = ('title', 'user__email')
    date_hierarchy = 'date'
    list_select_related = ('user', 'category')


@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    list_display = ('name', 'amount', 'due_date', 'status', 'user')
    list_filter = ('status', 'due_date')
    search_fields = ('name', 'user__email')
    list_select_related = ('user',)


@admin.register(PaymentProof)
class PaymentProofAdmin(admin.ModelAdmin):
    list_display = ('bill', 'user', 'status', 'reviewed_by', 'created_at')
    list_filter = ('status',)
    search_fields = ('bill__name', 'user__email')
    list_select_related = ('bill', 'user', 'reviewed_by')
