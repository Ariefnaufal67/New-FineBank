// Membuat koleksi Postman: node generate.js
const fs = require('fs');
const J = [{ key: 'Content-Type', value: 'application/json' }];
const bearer = (v) => ({ type: 'bearer', bearer: [{ key: 'token', value: `{{${v}}}`, type: 'string' }] });
const mkUrl = (path, query = []) => ({
  raw: `{{baseUrl}}${path}${query.length ? '?' + query.map((q) => `${q.key}=${q.value}`).join('&') : ''}`,
  host: ['{{baseUrl}}'], path: path.split('/').filter(Boolean), query,
});
const status = (c, label) => `pm.test('${label || 'Status ' + c}', () => pm.response.to.have.status(${c}));`;
const item = (name, method, path, { body, query, as, tests = [], desc } = {}) => ({
  name,
  event: tests.length ? [{ listen: 'test', script: { type: 'text/javascript', exec: tests } }] : undefined,
  request: {
    method, header: body ? J : [], description: desc,
    auth: as ? bearer(as) : { type: 'noauth' },
    body: body ? { mode: 'raw', raw: JSON.stringify(body, null, 2) } : undefined,
    url: mkUrl(path, query),
  },
});
const set = (k, expr) => `pm.collectionVariables.set('${k}', ${expr});`;
const j = 'pm.response.json()';

const collection = {
  info: {
    name: 'FineBank API (Django)',
    schema: 'https://schema.getpostman.com/json/collection/v2.1.0/collection.json',
    description: 'Jalankan folder 0 sampai 9 berurutan (Collection Runner). Folder 10 (Throttling) jalankan terakhir.\n' +
      'Prasyarat: python manage.py import_csv && python manage.py seed_demo. Akun: arief@ (user), staff@ (admin), admin2@ (superadmin), sandi password123.\n' +
      'Catatan: login dibatasi 10 kali per 15 menit per IP. Jika muncul 429 saat mengulang, tunggu 15 menit atau restart server.',
  },
  variable: ['baseUrl:http://localhost:8000', 'userToken', 'adminToken', 'superToken', 'ariefId', 'staffId', 'superId', 'newEmail', 'newUserId',
    'categoryId', 'expenseId', 'billId', 'paymentId'].map((s) => { const [key, value = ''] = s.split(/:(.*)/s); return { key, value }; }),
  item: [
    { name: '0. Health', item: [item('GET /health', 'GET', '/health', { tests: [status(200), "pm.test('status ok', () => pm.expect(pm.response.json().status).to.eql('ok'));"] })] },

    { name: '1. Auth', item: [
      item('Register user baru', 'POST', '/api/auth/register', { body: { name: 'Tester Postman', email: 'postman{{$timestamp}}@test.dev', password: 'password123' },
        tests: [status(201), set('newEmail', `${j}.data.user.email`), set('newUserId', `${j}.data.user.id`),
          "pm.test('role default user', () => pm.expect(pm.response.json().data.user.role).to.eql('user'));",
          "pm.test('password tidak bocor', () => pm.expect(JSON.stringify(pm.response.json())).to.not.include('password'));"] }),
      item('Register - email sudah terdaftar (409)', 'POST', '/api/auth/register', { body: { name: 'Dobel', email: '{{newEmail}}', password: 'password123' }, tests: [status(409)] }),
      item('Register - validasi gagal (400)', 'POST', '/api/auth/register', { body: { name: 'A', email: 'bukan-email', password: '123' },
        tests: [status(400), "pm.test('ada errors[]', () => pm.expect(pm.response.json().errors.length).to.be.above(0));"] }),
      item('Login user (arief)', 'POST', '/api/auth/login', { body: { email: 'arief@finebank.test', password: 'password123' },
        tests: [status(200), set('userToken', `${j}.data.token`), set('ariefId', `${j}.data.user.id`),
          "pm.test('role user', () => pm.expect(pm.response.json().data.user.role).to.eql('user'));"] }),
      item('Login admin (staff)', 'POST', '/api/auth/login', { body: { email: 'staff@finebank.test', password: 'password123' },
        tests: [status(200), set('adminToken', `${j}.data.token`), set('staffId', `${j}.data.user.id`),
          "pm.test('role admin', () => pm.expect(pm.response.json().data.user.role).to.eql('admin'));"] }),
      item('Login superadmin (admin2)', 'POST', '/api/auth/login', { body: { email: 'admin2@finebank.test', password: 'password123' },
        tests: [status(200), set('superToken', `${j}.data.token`), set('superId', `${j}.data.user.id`),
          "pm.test('role superadmin', () => pm.expect(pm.response.json().data.user.role).to.eql('superadmin'));"] }),
      item('Login salah (401)', 'POST', '/api/auth/login', { body: { email: 'arief@finebank.test', password: 'salah-salah' }, tests: [status(401)] }),
      item('Me', 'GET', '/api/auth/me', { as: 'userToken', tests: [status(200), "pm.test('email arief', () => pm.expect(pm.response.json().data.email).to.eql('arief@finebank.test'));"] }),
      item('Tanpa token (401)', 'GET', '/api/auth/me', { tests: [status(401)] }),
    ] },

    { name: '2. Categories (user)', item: [
      item('Buat kategori', 'POST', '/api/categories', { as: 'userToken', body: { name: 'Hiburan {{$timestamp}}' }, tests: [status(201), set('categoryId', `${j}.data.id`)] }),
      item('Kategori duplikat (409)', 'POST', '/api/categories', { as: 'userToken', body: { name: 'Hiburan {{$timestamp}}' }, desc: 'Nama berbeda karena timestamp; hanya memastikan 201/409 valid.', tests: ["pm.test('201 atau 409', () => pm.expect([201, 409]).to.include(pm.response.code));"] }),
      item('Daftar kategori', 'GET', '/api/categories', { as: 'userToken', tests: [status(200), "pm.test('array', () => pm.expect(pm.response.json().data).to.be.an('array'));"] }),
      item('Ubah kategori', 'PUT', '/api/categories/{{categoryId}}', { as: 'userToken', body: { name: 'Hiburan (ubah) {{$timestamp}}' }, tests: [status(200)] }),
    ] },

    { name: '3. Expenses (user)', item: [
      item('Buat expense', 'POST', '/api/expenses', { as: 'userToken', body: { title: 'Nonton bioskop', amount: 55000, date: '2026-10-25', categoryId: '{{categoryId}}' },
        tests: [status(201), set('expenseId', `${j}.data.id`), "pm.test('kategori ikut (JOIN)', () => pm.expect(pm.response.json().data.category.id).to.exist);"] }),
      item('Validasi gagal (400)', 'POST', '/api/expenses', { as: 'userToken', body: { title: '', amount: -5, date: 'kemarin' }, tests: [status(400)] }),
      item('List + pagination', 'GET', '/api/expenses', { as: 'userToken', query: [{ key: 'page', value: '1' }, { key: 'limit', value: '5' }],
        tests: [status(200), "const m = pm.response.json().meta; pm.test('meta pagination', () => { pm.expect(m.limit).to.eql(5); pm.expect(m).to.have.property('totalPages'); });"] }),
      item('Limit maksimum 100', 'GET', '/api/expenses', { as: 'userToken', query: [{ key: 'limit', value: '500' }], tests: [status(200), "pm.test('dibatasi 100', () => pm.expect(pm.response.json().meta.limit).to.eql(100));"] }),
      item('Filter (q, nominal, tanggal, sort)', 'GET', '/api/expenses', { as: 'userToken', query: [{ key: 'q', value: 'nonton' }, { key: 'minAmount', value: '10000' }, { key: 'from', value: '2026-10-01' }, { key: 'sort', value: '-amount' }],
        tests: [status(200), "pm.test('hasil cocok', () => pm.response.json().data.forEach(e => pm.expect(e.title.toLowerCase()).to.include('nonton')));"] }),
      item('Detail', 'GET', '/api/expenses/{{expenseId}}', { as: 'userToken', tests: [status(200)] }),
      item('Update (PUT parsial)', 'PUT', '/api/expenses/{{expenseId}}', { as: 'userToken', body: { amount: 60000 }, tests: [status(200), "pm.test('amount berubah', () => pm.expect(pm.response.json().data.amount).to.eql(60000));"] }),
      item('Summary (GROUP BY)', 'GET', '/api/expenses/summary', { as: 'userToken', tests: [status(200), "pm.test('ada byCategory', () => pm.expect(pm.response.json().data).to.have.property('byCategory'));"] }),
      item('Admin TIDAK melihat expense user (404)', 'GET', '/api/expenses/{{expenseId}}', { as: 'adminToken', tests: [status(404)] }),
      item('Superadmin melihat semua (200)', 'GET', '/api/expenses/{{expenseId}}', { as: 'superToken', tests: [status(200)] }),
    ] },

    { name: '4. Bills (user)', item: [
      item('Buat bill', 'POST', '/api/bills', { as: 'userToken', body: { name: 'Netflix {{$timestamp}}', amount: 54000, dueDate: '2026-10-01' }, tests: [status(201), set('billId', `${j}.data.id`), "pm.test('belum dibayar', () => pm.expect(pm.response.json().data.status).to.eql('unpaid'));"] }),
      item('User tidak bisa set status paid (403)', 'PUT', '/api/bills/{{billId}}', { as: 'userToken', body: { status: 'paid' }, tests: [status(403)] }),
      item('User tidak bisa catat bukti (403)', 'POST', '/api/bills/{{billId}}/proof', { as: 'userToken', body: { note: 'Sudah transfer BCA' }, tests: [status(403)] }),
      item('User tidak bisa Tandai Lunas (403)', 'POST', '/api/bills/{{billId}}/pay', { as: 'userToken', tests: [status(403)] }),
      item('List overdue', 'GET', '/api/bills', { as: 'userToken', query: [{ key: 'status', value: 'overdue' }], tests: [status(200)] }),
    ] },

    { name: '5. Admin mencatat bukti pembayaran', item: [
      item('Admin membaca semua tagihan', 'GET', '/api/bills', { as: 'adminToken', tests: [status(200), "pm.test('ada ownerName', () => pm.expect(pm.response.json().data[0]).to.have.property('ownerName'));"] }),
      item('Admin tidak bisa ubah tagihan user (404)', 'PUT', '/api/bills/{{billId}}', { as: 'adminToken', body: { name: 'x' }, tests: [status(404)] }),
      item('Bukti terlalu pendek (400)', 'POST', '/api/bills/{{billId}}/proof', { as: 'adminToken', body: { note: 'x' }, tests: [status(400)] }),
      item('Admin catat pembayaran + bukti', 'POST', '/api/bills/{{billId}}/proof', { as: 'adminToken', body: { note: 'Transfer BCA 1 Okt Rp54.000', proofUrl: 'https://example.com/bukti.jpg' },
        tests: [status(201), set('paymentId', `${j}.data.id`), "pm.test('dicatat admin', () => pm.expect(pm.response.json().data.reviewedBy).to.exist);"] }),
      item('Catat lagi: sudah lunas (409)', 'POST', '/api/bills/{{billId}}/proof', { as: 'adminToken', body: { note: 'dobel catat' }, tests: [status(409)] }),
      item('User melihat tagihan sudah Lunas', 'GET', '/api/bills/{{billId}}', { as: 'userToken', tests: [status(200), "pm.test('paid', () => pm.expect(pm.response.json().data.status).to.eql('paid'));"] }),
      item('User melihat bukti (hanya baca)', 'GET', '/api/payments', { as: 'userToken', tests: [status(200), "pm.test('ada bukti', () => pm.expect(pm.response.json().meta.total).to.be.above(0));"] }),
      item('User tidak bisa hapus bukti (405)', 'DELETE', '/api/payments/{{paymentId}}', { as: 'userToken', tests: [status(405)] }),
    ] },

    { name: '6. Users & role', item: [
      item('User biasa ke /users (403)', 'GET', '/api/users', { as: 'userToken', tests: [status(403)] }),
      item('Admin melihat daftar user', 'GET', '/api/users', { as: 'adminToken', tests: [status(200), "pm.test('superadmin tersembunyi', () => pm.response.json().data.forEach(u => pm.expect(u.role).to.not.eql('superadmin')));"] }),
      item('Admin tidak bisa ubah role (403)', 'PATCH', '/api/users/{{newUserId}}', { as: 'adminToken', body: { role: 'admin' }, tests: [status(403)] }),
      item('Admin tidak bisa hapus user (403)', 'DELETE', '/api/users/{{newUserId}}', { as: 'adminToken', tests: [status(403)] }),
      item('Superadmin ubah role -> admin', 'PATCH', '/api/users/{{newUserId}}', { as: 'superToken', body: { role: 'admin' }, tests: [status(200), "pm.test('jadi admin', () => pm.expect(pm.response.json().data.role).to.eql('admin'));"] }),
      item('Superadmin kembalikan role -> user', 'PATCH', '/api/users/{{newUserId}}', { as: 'superToken', body: { role: 'user' }, tests: [status(200)] }),
      item('Superadmin tidak bisa ubah role sendiri (400)', 'PATCH', '/api/users/{{superId}}', { as: 'superToken', body: { role: 'user' }, tests: [status(400)] }),
      item('Role tidak valid (400)', 'PATCH', '/api/users/{{newUserId}}', { as: 'superToken', body: { role: 'dewa' }, tests: [status(400)] }),
    ] },

    { name: '7. Impor pengeluaran per user (admin)', item: [
      item('Admin impor untuk user tertentu', 'POST', '/api/users/{{ariefId}}/import-expenses', { as: 'adminToken',
        body: { expenses: [{ title: 'Impor Postman {{$timestamp}}', amount: 21000, date: '2026-10-30', category: 'Makanan' }, { title: 'Baris rusak', amount: 'abc', date: '2026-10-30' }] },
        desc: 'Untuk impor file CSV: ubah Body ke form-data, key "file" bertipe File (kolom: title,amount,date,category,note).',
        tests: [status(201), "const d = pm.response.json().data; pm.test('1 masuk, 1 gagal', () => { pm.expect(d.created).to.eql(1); pm.expect(d.failed).to.eql(1); });"] }),
      item('User tidak bisa impor (403)', 'POST', '/api/users/{{newUserId}}/import-expenses', { as: 'userToken', body: { expenses: [] }, tests: [status(403)] }),
      item('Admin tidak bisa impor untuk admin lain (403)', 'POST', '/api/users/{{staffId}}/import-expenses', { as: 'adminToken', body: { expenses: [] }, tests: [status(403)] }),
      item('Admin tidak melihat superadmin (404)', 'POST', '/api/users/{{superId}}/import-expenses', { as: 'adminToken', body: { expenses: [] }, tests: [status(404)] }),
      item('Body kosong (400)', 'POST', '/api/users/{{ariefId}}/import-expenses', { as: 'adminToken', body: {}, tests: [status(400)] }),
    ] },

    { name: '8. Statistik (agregasi)', item: [
      item('Statistik pengeluaran (user)', 'GET', '/api/stats/expenses', { as: 'userToken', tests: [status(200), "const d = pm.response.json().data; pm.test('field agregasi', () => ['expenseCount','total','min','max','avg','cheapest','mostExpensive','byCategory','monthly'].forEach(k => pm.expect(d).to.have.property(k)));"] }),
      item('Statistik tagihan', 'GET', '/api/stats/bills', { as: 'userToken', tests: [status(200)] }),
      item('Statistik user: user biasa (403)', 'GET', '/api/stats/users', { as: 'userToken', tests: [status(403)] }),
      item('Statistik user: admin (200)', 'GET', '/api/stats/users', { as: 'adminToken', tests: [status(200), "pm.test('ada topUsers', () => pm.expect(pm.response.json().data).to.have.property('topUsers'));"] }),
    ] },

    { name: '9. Pembersihan', item: [
      item('Hapus expense', 'DELETE', '/api/expenses/{{expenseId}}', { as: 'userToken', tests: [status(204)] }),
      item('Hapus expense lagi (404)', 'DELETE', '/api/expenses/{{expenseId}}', { as: 'userToken', tests: [status(404)] }),
      item('Hapus bill', 'DELETE', '/api/bills/{{billId}}', { as: 'userToken', tests: [status(204)] }),
      item('Hapus kategori', 'DELETE', '/api/categories/{{categoryId}}', { as: 'userToken', tests: [status(204)] }),
      item('Superadmin hapus user uji', 'DELETE', '/api/users/{{newUserId}}', { as: 'superToken', tests: [status(204)] }),
      item('Superadmin tidak bisa hapus diri sendiri (400)', 'DELETE', '/api/users/{{superId}}', { as: 'superToken', tests: [status(400)] }),
    ] },

    { name: '10. Throttling (jalankan TERAKHIR)', item: [
      item('Login salah berulang -> 429', 'POST', '/api/auth/login', { body: { email: 'throttle@test.dev', password: 'salah-salah' },
        desc: 'Kirim ulang 11 kali (atau Runner dengan 11 iterasi). Dua belas request pertama: 401, lalu 429.',
        tests: ["pm.test('401 atau 429', () => pm.expect([401, 429]).to.include(pm.response.code));", "if (pm.response.code === 429) pm.test('pesan throttling', () => pm.expect(pm.response.json().message).to.include('Terlalu banyak request'));"] }),
    ] },
  ],
};
const env = (name, base) => ({ id: name, name, values: [{ key: 'baseUrl', value: base, enabled: true }], _postman_variable_scope: 'environment' });
fs.writeFileSync('FineBank-Django.postman_collection.json', JSON.stringify(collection, null, 2));
fs.writeFileSync('Local.postman_environment.json', JSON.stringify(env('FineBank Local', 'http://localhost:8000'), null, 2));
fs.writeFileSync('Vercel.postman_environment.json', JSON.stringify(env('FineBank Vercel', 'https://GANTI-NAMA-PROJECT.vercel.app'), null, 2));
console.log('ok');
