# Network Inspector

Windows'ta çalışan, sistem genelindeki dış ağ bağlantılarını uygulama ve süreçlerle ilişkilendirerek yerel bir arayüzde incelemeyi hedefleyen network inspection aracı.

> Durum: HTTP istek/yanıt inceleme, WebSocket kareleri, içerik araması, CA kurulumu, RAM ring buffer ve şifreli kayıt kullanılabilir. Bu sürüm nihai spesifikasyonun tamamı değildir: canlı SSE parçalama, genel TCP/UDP/DNS decoder'ları ve `.mitm` dışa aktarımı henüz yoktur. SSE içeriği yanıt tamamlanınca gösterilir.

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

Üst çubuktaki **Kayıt** düğmesiyle en az 8 karakterli bir parola belirleyip kaydı başlatın. Uygulama seçimi yoksa tüm uygulamalar, seçim varsa yalnızca seçilen uygulamalar kaydedilir. Kapsam başlangıçta sabitlenir; önceden açılmış oturumlar canlı kayda alınmaz. Capture ayrıca çalışıyor olmalıdır. **Kaydı durdur** dosyayı tamamlar.

**Filtrelenmiş RAM’i kaydet**, mevcut arama ve uygulama filtresine uyan geçmiş RAM oturumlarını ayrı bir şifreli dosyaya aktarır. Kayıt listesindeki **Aç**, capture ve kayıt durduktan sonra parolayla RAM listesini değiştirir. Yanlış parola veya bozuk dosyada mevcut RAM korunur. **Şifreli indir** dosyanın yedeğini indirir; başka bilgisayarda kullanmak için dosyayı `recordings/` içine yerleştirin.

Dosyalar `recordings/<kimlik>.awp` biçimindedir: scrypt anahtar türetimi, AES-256-GCM doğrulamalı şifreleme ve sıralı parça doğrulaması kullanılır. Parola dosyada tutulmaz; kaybolursa kurtarılamaz. API anahtarları ve özel mesajlar içerebilir. Tamamlanmamış dosyalar sessizce yüklenmez. Dosya başına sınır 1 GB, yazma kuyruğu 96 MB'dır; disk dolması/yetişememesi görünür hata verir ve capture'dan bağımsız olarak kaydı durdurur.

## Hata tanılama ve sınırlar

`.runtime/diagnostics.log` ve dönen üç yedek, uygulama yaşam döngüsünü ve yakalanan hataların tür/kod konumlarını saklar; trafik gövdeleri, parolalar ve hata mesajlarındaki olası sırlar bu dosyaya yazılmaz. İşletim sisteminin süreci zorla sonlandırması uygulama traceback'i bırakmayabilir. Eski log yoksa kapanış nedeni kesin olarak belirlenemez.

RAM ring buffer tahmini bütçesi 512 MB, oturum sayısı 100.000, gövde yakalama sınırı 10 MB'dır. Bunlar toplam süreç RAM'i için sert bir işletim sistemi limiti değildir. WebSocket geçmişi ayrıca 10.000 kareyle sınırlıdır. Arayüz 1,5 saniyede bir yenilenir; tablo en son 1.000 sonucu gösterir, içerik araması backend'deki RAM verisini tarar. `start.bat` frontend'i her çalıştırmada yeniden derler; güncel kaynaklar eski bir build nedeniyle gizlenmez.
