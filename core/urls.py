from django.http import JsonResponse
from django.shortcuts import render
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.include_root_view = False
router.register('categories', views.CategoryViewSet, basename='category')
router.register('expenses', views.ExpenseViewSet, basename='expense')
router.register('bills', views.BillViewSet, basename='bill')
router.register('users', views.UserViewSet, basename='user')
router.register('payments', views.PaymentProofViewSet, basename='payment')

api_patterns = [
    path('auth/register', views.RegisterView.as_view()),
    path('auth/login', views.LoginView.as_view()),
    path('auth/me', views.MeView.as_view()),
    path('stats/expenses', views.ExpenseStatsView.as_view()),
    path('stats/bills', views.BillStatsView.as_view()),
    path('stats/users', views.UserStatsView.as_view()),
    path('', include(router.urls)),
]


def page(template):
    return lambda request: render(request, template)


def health(request):
    return JsonResponse({'status': 'ok'})


urlpatterns = [
    path('', page('core/home.html'), name='home'),
    path('statistik', page('core/statistik.html'), name='statistik'),
    path('pengeluaran', page('core/pengeluaran.html'), name='pengeluaran'),
    path('tagihan', page('core/tagihan.html'), name='tagihan'),
    path('pembayaran', page('core/pembayaran.html'), name='pembayaran'),
    path('impor', page('core/impor.html'), name='impor'),
    path('health', health, name='health'),
    path('api/', include(api_patterns)),
]
