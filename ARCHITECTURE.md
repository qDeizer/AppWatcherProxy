# Network Inspector Architecture

## Değişmez sınırlar

1. Çekirdek servis veya ürün adı bilmez; yalnızca genel protokol ve içerik formatlarını tanır.
2. Ayrıştırılmış veri ham veriye eklenir. Ham payload, yapılandırılmış kesme sınırına kadar her zaman korunur.
3. Capture yaşam döngüsü fail-open tasarlanır. Sistem proxy ayarı yazılmaz; kalıcı yönlendirme yapılmaz.

## Mevcut katmanlar

```text
React UI ── REST + WebSocket ── FastAPI
                                  │
                         RAM SessionBuffer
                                  │
                         CaptureEngine adapter
                                  │
                      mitmproxy local / WinDivert
```

`SessionBuffer`, hem session sayısı hem tahmini seri hale getirilmiş bayt büyüklüğü ile sınırlı bir `OrderedDict` kullanır. Liste WebSocket mesajlarında yalnızca özet taşır; tam session için REST uç noktası ayrıdır.

Veri modeli `Application → Process → Connection → Session → Request/Response → Stream → Frame → Payload` hiyerarşisini doğrudan temsil eder. `Connection`, HTTP olmayan ve uzun yaşayan protokoller için birinci sınıf varlıktır.

## Capture yaşam döngüsü

`CaptureEngine`, `DumpMaster`'ı subprocess olarak değil aynı Python event loop'u içinde çalıştırır. mitmproxy yalnızca kullanıcı Başlat dediğinde import edilir ve local mode tüm makine için açılır. Başlatma başarısız olursa durum `error` olur, UI sebebi gösterir ve ağ ayarı kalıcılaştırılmaz.

`start.bat`, backend'i başlatmadan önce CA dosyasını deterministik olarak `~/.mitmproxy` altında üretir. Dosyanın SHA-1 parmak izi CurrentUser ve LocalMachine kök depolarındaki sertifikalarla karşılaştırılır. Tam eşleşme LocalMachine deposunda yoksa kullanıcıya güven sınırı açıkça anlatılır, onaydan sonra `certutil -addstore -f Root` çalıştırılır ve sonuç yeniden doğrulanır. Konu adı aynı olan eski sertifikalar eşleşme sayılmaz ve otomatik silinmez.

Addon şimdilik tamamlanan HTTP flow'larını RAM modeline dönüştürür ve TLS/sertifika içeren flow hatalarını `Encrypted` olarak görünür kılar. Streaming wrapper, DNS, ham TCP, QUIC metadata ve ayrıntılı içerik sezme sonraki aşamalarda eklenir.

## Fail-open ve kurtarma

Backend başlamadan önce bilinen UDP/443 firewall kuralını kaldırır. Başlangıçtan sonra ayrı bir watchdog ana PID'yi izler. Ana süreç beklenmedik biçimde kaybolursa watchdog aynı idempotent temizliği çağırır. Normal kapanış capture → watchdog → network cleanup sırasını izler.

Runtime state ana PID ile birlikte süreç başlangıç zamanını da saklar. İkinci bir instance canlı PID ve başlangıç zamanı eşleşmesi görürse mevcut instance'ın cleanup veya watchdog durumuna dokunmadan başlamayı reddeder; böylece PID yeniden kullanımı ve eşzamanlı başlangıçlar stale-state temizliğiyle karıştırılmaz.

`.runtime/state.json` yalnızca süreç kimlikleri ve Network Inspector'ın geçici sistem davranışını içerir; trafik verisi içermez. `stop.bat` bu dosyadaki kesin PID'leri hedefler, genel Python/mitmproxy süreçlerini öldürmez.

## Disk politikası

Çalışma zamanı durumu dışında capture verisi yazılmaz. `recordings/` kaynak ağacında oluşturulmaz. Şifreli recorder eklenirken manifest dışında tüm session akışı Argon2id + XChaCha20-Poly1305 veya AES-256-GCM ile parça bazlı şifrelenecektir.

## Sonraki uygulama sırası

1. mitmproxy hook uyumluluğunu Windows üzerinde gerçek local capture ile doğrulama
2. CA üretim/kurulum/kaldırma ve Setup ekranı
3. içerik sezme + decompress + parser zinciri
4. response streaming, SSE, WebSocket ve gRPC frame modeli
5. gelişmiş uygulama filtresi ve arama indeksi
6. şifreli recorder ve güvenli dışa aktarma
