import { useEffect, useRef, useState } from 'react'
import { api } from '../api'

export function RecordingPanel({ applications, query, onClose, onChanged }: {
  applications: string[]; query: string; onClose: () => void; onChanged: () => Promise<void>
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [password, setPassword] = useState('')
  const [items, setItems] = useState<{id: string; size: number; modified: string}[]>([])
  const [active, setActive] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  async function refresh() {
    const data = await api.recordings()
    setItems(data.items); setActive(data.active)
    if (data.error) setError(data.error)
  }
  useEffect(() => {
    dialog.current?.showModal()
    void refresh().catch((reason) => setError(String(reason)))
  }, [])
  async function run(action: () => Promise<unknown>, message: string) {
    setBusy(true); setError(''); setNotice('')
    try {
      await action(); setPassword('')
      await refresh(); await onChanged(); setNotice(message)
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(false) }
  }
  async function downloadMitm(id: string) {
    if (!window.confirm('Bu işlem şifresi çözülmüş .mitm dosyası indirir. API anahtarları ve özel mesajlar düz metin olabilir. Devam edilsin mi?')) return
    setBusy(true); setError(''); setNotice('')
    try {
      const result = await api.recordMitm(id, password)
      const url = URL.createObjectURL(result.blob)
      const link = document.createElement('a')
      link.href = url; link.download = `${id}.mitm`; link.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
      setPassword('')
      setNotice(`${result.exported} oturum .mitm dosyasına aktarıldı${result.skipped ? `; ${result.skipped} eksik veya desteklenmeyen oturum atlandı` : ''}. Dosya şifresizdir.`)
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(false) }
  }
  return <dialog ref={dialog} aria-labelledby="recording-heading" className="recording-dialog" onCancel={(event) => { if (busy) event.preventDefault(); else onClose() }}>
    <div className="panel-heading"><h2 id="recording-heading">Şifreli kayıtlar</h2><button className="button" disabled={busy} onClick={onClose}>Kapat</button></div>
    <div className="recording-content">
      <p>⚠ Sensitive Data — Trafik API anahtarı ve özel mesaj içerebilir. scrypt + AES-256-GCM ile şifrelenir. Parola kaybolursa kayıt açılamaz.</p>
      <label>Parola (en az 8 karakter)<input autoFocus type="password" autoComplete="new-password" minLength={8} maxLength={1024} value={password} onChange={(event) => setPassword(event.target.value)} /></label>
      <p>Kapsam: {applications.length ? applications.join(', ') : 'Tüm uygulamalar'}. Canlı kayıt yalnızca başlatıldıktan sonra açılan oturumları içerir; kapsam kayıt boyunca sabittir.</p>
      {error && <p role="alert" className="recording-error">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <div className="recording-actions">
        <button className={`button ${active ? 'button-danger' : 'button-primary'}`} disabled={busy || (!active && password.length < 8)} onClick={() => void run(() => active ? api.recordStop() : api.recordStart(password, applications), active ? 'Kayıt durduruldu.' : 'Kayıt açık. Capture başlatıldığında yeni trafik kaydedilir.')}>
          {busy ? 'İşleniyor…' : active ? '● Kaydı durdur' : 'Kaydı başlat'}
        </button>
        <button className="button" disabled={busy || password.length < 8} onClick={() => void run(() => api.recordExport(password, applications, query), 'Filtreye uyan RAM oturumları şifreli kaydedildi.')}>Filtrelenmiş RAM’i kaydet</button>
        {!active && <button className="button" disabled={busy} onClick={() => void run(api.recordStop, 'Kayıt dosyası kapatıldı.')}>Açık dosyayı kapat</button>}
      </div>
      <h3>Bilgisayardaki kayıtlar</h3>
      <p>Açma işlemi RAM listesini değiştirir. Önce capture ve kaydı durdurun. Dosyalar recordings klasöründedir.</p>
      {!items.length ? <p>Henüz kayıt yok.</p> : <ul className="recording-list">{items.map((item) => <li key={item.id}>
        <span>{new Date(item.modified).toLocaleString('tr-TR')} · {(item.size / 1024).toFixed(1)} KB <small>{item.id}</small></span>
        <button className="button" disabled={busy || active || password.length < 8} onClick={() => {
          if (window.confirm('RAM listesini bu kayıtla değiştirmek istiyor musunuz?')) void run(() => api.recordOpen(item.id, password), 'Kayıt RAM’e açıldı; ana tabloda inceleyebilirsiniz.')
        }}>Aç</button>
        {!active && <a className="button" href={`/api/recordings/${item.id}/download`} download>Şifreli indir</a>}
        {!active && <button className="button" disabled={busy || password.length < 8} onClick={() => void downloadMitm(item.id)}>Şifresini çöz · .mitm indir</button>}
      </li>)}</ul>}
    </div>
  </dialog>
}
