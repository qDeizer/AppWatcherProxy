# Network Inspector

Windows'ta çalışan, sistem genelindeki dış ağ bağlantılarını uygulama ve süreçlerle ilişkilendirerek yerel bir arayüzde incelemeyi hedefleyen network inspection aracı.

> Durum: İlk çalışan iskelet hazır. FastAPI yaşam döngüsü, fail-open kurtarma/watchdog, RAM ring buffer, mitmproxy local-mode adaptörü ve React arayüz temeli bulunuyor. Protokol decoder'ları, sertifika kurulum akışı, streaming ve şifreli kayıt sonraki aşamalardır.

## İlk çalıştırma

1. Windows'ta `start.bat` dosyasına çift tıklayın.
2. UAC penceresini onaylayın. mitmproxy local capture, WinDivert nedeniyle yönetici yetkisi gerektirir.
3. İlk çalıştırmada Python sanal ortamı ve frontend bağımlılıkları kurulur. Bu birkaç dakika sürebilir.
4. `start.bat`, mitmproxy CA dosyasını yoksa üretir ve parmak izini Windows güven deposuyla karşılaştırır.
5. CA henüz güvenilir değilse, Yerel Makine `Trusted Root` deposuna kurmadan önce konsolda açıkça onay ister. Onay verilmezse capture başlatılmaz.
6. Backend hazır olduğunda `http://127.0.0.1:43110` varsayılan tarayıcıda açılır.

Python 3.12+ ve Node.js 20+ gerekir. Uygulama internet erişimi için sistem proxy ayarlarını değiştirmez.

## Geliştirme

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
cd frontend
npm install
npm run dev
```

Ayrı bir terminalde:

```powershell
.\.venv\Scripts\python.exe -m backend.main
```

Vite geliştirme sunucusu `/api` ve `/ws` isteklerini `127.0.0.1:43110` adresine yönlendirir.

## Güvenli kapatma

Normal kapanışta backend capture'ı durdurur, watchdog'u kapatır, geçici çalışma durumunu siler, olası UDP/443 firewall kuralını kaldırır ve proxy durumunu yalnızca doğrular.

Ana süreç zorla kapatılırsa ayrı watchdog aynı temizliği çalıştırır. Herhangi bir şüphede yönetici olarak `stop.bat` çalıştırılabilir; betik yalnızca `.runtime/state.json` içindeki bu uygulamaya ait PID'leri hedefler ve adı sabit olan Network Inspector firewall kuralını kaldırır.

## Sertifika

HTTPS gövdelerinin çözülebilmesi için mitmproxy CA sertifikası Windows güven deposuna kurulmalıdır. `start.bat` sertifikayı otomatik üretir, tam parmak iziyle kontrol eder ve eksikse kullanıcı onayından sonra Yerel Makine güvenilir kök deposuna kurar. Aynı sertifika zaten kuruluysa soru sormadan devam eder. Eski veya eşleşmeyen sertifikalar otomatik silinmez.

Node.js, Python requests, curl, Go veya Java gibi çalışma zamanları Windows güven deposunu kullanmayabilir. İlerleyen Setup ekranı yalnızca ilgili `NODE_EXTRA_CA_CERTS`, `REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`, `CURL_CA_BUNDLE` ve `keytool` bilgilerini gösterecek; hedef uygulamaları otomatik değiştirmeyecektir.

## Test ve kalite kontrolleri

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check backend tests
cd frontend
npm run lint
npm run build
```

## Gizlilik

- Capture verisi varsayılan olarak yalnızca RAM'dedir.
- Kayıt kapalıyken `recordings/` oluşturulmaz.
- Uzak font, script, CDN ve telemetri yoktur.
- Tanınmayan payload gelecekte de ham hali korunarak gösterilecektir.
