# Network Inspector

Windows'ta çalışan, sistem genelindeki dış ağ bağlantılarını uygulama ve süreçlerle ilişkilendirerek yerel bir arayüzde incelemeyi hedefleyen network inspection aracı.

> Durum: HTTP istek/yanıt inceleme, WebSocket kareleri, canlı SSE olayları, içerik araması, CA kurulumu, RAM ring buffer, şifreli kayıt ve `.mitm` dışa aktarımı kullanılabilir. Genel TCP/UDP/DNS decoder'ları gibi diğer nihai spesifikasyon maddeleri henüz tamamlanmamıştır.

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

## Kayıt ve yeniden açma

Üst çubuktaki **Kayıt** düğmesi kaydı tek tıkla başlatır; **Kaydı durdur** dosyayı tamamlar. Parola sorulmaz. Uygulama seçimi yoksa tüm uygulamalar, seçim varsa yalnızca seçilen uygulamalar kaydedilir. Kapsam başlangıçta sabitlenir; önceden açılmış oturumlar canlı kayda alınmaz. Trafiği yakalamak için **Başlat** ile capture da çalışıyor olmalıdır. **Kayıtlar** düğmesi dosya listesini açar.

**Filtrelenmiş RAM’i kaydet**, mevcut arama ve uygulama filtresine uyan geçmiş RAM oturumlarını ayrı bir şifreli dosyaya aktarır. Kayıt listesindeki **Aç**, capture ve kayıt durduktan sonra RAM listesini değiştirir. Bozuk dosyada mevcut RAM korunur. **Şifreli indir** dosyanın yedeğini indirir. Yeni kayıtlar aynı Windows hesabında parola olmadan açılır; başka hesapta veya bilgisayarda açmak için orijinal hesapta `.mitm` dışa aktarımı yapın.

Dosyalar `recordings/<kimlik>.awp` biçimindedir. Yeni `AWP2` kayıtlarında rastgele AES-256-GCM anahtarı Windows DPAPI ile mevcut kullanıcı hesabına bağlanır; parola oluşturulmaz veya istenmez. Eski `AWP1` kayıtları değişmeden kalır ve yalnızca onlar açılırken eski parolaları sorulur. Kayıtlar API anahtarları ve özel mesajlar içerebilir. Tamamlanmamış dosyalar sessizce yüklenmez. Dosya başına sınır 1 GB, yazma kuyruğu 96 MB'dır; disk dolması/yetişememesi görünür hata verir ve capture'dan bağımsız olarak kaydı durdurur.

**Şifresini çöz · .mitm indir**, tamamlanmış HTTP/WebSocket oturumlarını mitmproxy FlowReader ile açılabilen bir dosyaya dönüştürür. Yeni kayıtlarda parola sorulmaz. Dosya düz metindir ve özel mesajları/API anahtarlarını içerebilir; indirmeden önce ekranda uyarı gösterilir. Eksik, kesilmiş veya desteklenmeyen oturumlar atlanır ve sayıları gösterilir. İçerikler kayıt anındaki yakalama sınırıyla sınırlıdır. Dosya yalnızca indirme akışında oluşturulur; uygulama diske şifresiz kopya yazmaz.

SSE yanıtlarında `responseheaders` aşamasında passthrough akışı açılır; gelen baytlar ağa değiştirilmeden iletilirken `event`, `data`, `id`, `retry` alanları parça sınırlarından bağımsız çözümlenir ve olay tamamlanır tamamlanmaz Stream sekmesinde görünür. JSON `data` içeriği biçimlendirilir. Gzip/deflate SSE canlı çözülür; farklı içerik kodlamaları yanıt tamamlanınca çözümlenir, ham gövde her durumda korunur.

## Hata tanılama ve sınırlar

`.runtime/diagnostics.log` ve dönen üç yedek, uygulama yaşam döngüsünü ve yakalanan hataların tür/kod konumlarını saklar; trafik gövdeleri, parolalar ve hata mesajlarındaki olası sırlar bu dosyaya yazılmaz. İşletim sisteminin süreci zorla sonlandırması uygulama traceback'i bırakmayabilir. Eski log yoksa kapanış nedeni kesin olarak belirlenemez.

RAM ring buffer tahmini bütçesi 512 MB, oturum sayısı 100.000, gövde yakalama sınırı 10 MB'dır. Bunlar toplam süreç RAM'i için sert bir işletim sistemi limiti değildir. WebSocket geçmişi ayrıca 10.000 kareyle sınırlıdır. Arayüz 1,5 saniyede bir yenilenir; tablo en son 1.000 sonucu gösterir, içerik araması backend'deki RAM verisini tarar. `start.bat` frontend'i her çalıştırmada yeniden derler; güncel kaynaklar eski bir build nedeniyle gizlenmez.
