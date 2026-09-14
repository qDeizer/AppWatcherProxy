import { useEffect, useRef, useState } from 'react'
import { api } from '../api'

type RecordingItem = { id: string; size: number; modified: string; password_required: boolean }

export function RecordingPanel({ applications, query, onClose, onChanged }: {
  applications: string[]; query: string; onClose: () => void; onChanged: () => Promise<void>
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [items, setItems] = useState<RecordingItem[]>([])
  const [active, setActive] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  async function refresh() {
    const data = await api.recordings()
    setItems(data.items)
    setActive(data.active)
    if (data.error) setError(data.error)
  }

  useEffect(() => {
    dialog.current?.showModal()
    void refresh().catch((reason) => setError(String(reason)))
  }, [])

  async function run(action: () => Promise<unknown>, message: string) {
    setBusy(true); setError(''); setNotice('')
    try {
      await action()
      await refresh(); await onChanged(); setNotice(message)
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(false) }
  }

  function passwordFor(item: RecordingItem): string | null | undefined {
    if (!item.password_required) return null
    const value = window.prompt('Bu eski kayıt parola ile oluşturulmuş. Eski parolayı girin:')
    if (value === null) return undefined
    if (value.length >= 8) return value
    setError('Eski kayıt parolası en az 8 karakter olmalı.')
    return undefined
  }

  function open(item: RecordingItem) {
    if (!window.confirm('RAM listesini bu kayıtla değiştirmek istiyor musunuz?')) return
    const password = passwordFor(item)
    if (password === undefined) return
    void run(() => api.recordOpen(item.id, password), 'Kayıt RAM’e açıldı; ana tabloda inceleyebilirsiniz.')
  }

  async function downloadMitm(item: RecordingItem) {
    if (!window.confirm('Bu işlem şifresi çözülmüş .mitm dosyası indirir. API anahtarları ve özel mesajlar düz metin olabilir. Devam edilsin mi?')) return
    const password = passwordFor(item)
    if (password === undefined) return
    setBusy(true); setError(''); setNotice('')
    try {
      const result = await api.recordMitm(item.id, password)
      const url = URL.createObjectURL(result.blob)
      const link = document.createElement('a')
      link.href = url; link.download = `${item.id}.mitm`; link.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
      setNotice(`${result.exported} oturum .mitm dosyasına aktarıldı${result.skipped ? `; ${result.skipped} eksik veya desteklenmeyen oturum atlandı` : ''}. Dosya şifresizdir.`)
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(false) }
  }

  return <dialog ref={dialog} aria-labelledby="recording-heading" className="recording-dialog" onCancel={(event) => { if (busy) event.preventDefault(); else onClose() }}>
    <div className="panel-heading"><h2 id="recording-heading">Kayıtlar</h2><button className="button" disabled={busy} onClick={onClose}>Kapat</button></div>
    <div className="recording-content">
      <p>⚠ Sensitive Data — Trafik API anahtarı ve özel mesaj içerebilir. Yeni kayıtlar Windows hesabınızla şifrelenir; parola sormadan açılır.</p>
      <p>Kapsam: {applications.length ? applications.join(', ') : 'Tüm uygulamalar'}. Canlı kayıt yalnızca başlatıldıktan sonra açılan oturumları içerir; kapsam kayıt boyunca sabittir.</p>
      {error && <p role="alert" className="recording-error">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <div className="recording-actions">
        <button className={`button ${active ? 'button-danger' : 'button-primary'}`} disabled={busy} onClick={() => void run(() => active ? api.recordStop() : api.recordStart(applications), active ? 'Kayıt durduruldu.' : 'Kayıt açık. Capture başlatıldığında yeni trafik kaydedilir.')}>
          {busy ? 'İşleniyor…' : active ? '● Kaydı durdur' : 'Kaydı başlat'}
        </button>
        <button className="button" disabled={busy} onClick={() => void run(() => api.recordExport(applications, query), 'Filtreye uyan RAM oturumları şifreli kaydedildi.')}>Filtrelenmiş RAM’i kaydet</button>
        {!active && <button className="button" disabled={busy} onClick={() => void run(api.recordStop, 'Kayıt dosyası kapatıldı.')}>Açık dosyayı kapat</button>}
      </div>
      <h3>Bilgisayardaki kayıtlar</h3>
      <p>Açma işlemi RAM listesini değiştirir. Önce capture ve kaydı durdurun. Dosyalar recordings klasöründedir.</p>
      {!items.length ? <p>Henüz kayıt yok.</p> : <ul className="recording-list">{items.map((item) => <li key={item.id}>
        <span>{new Date(item.modified).toLocaleString('tr-TR')} · {(item.size / 1024).toFixed(1)} KB <small>{item.id}{item.password_required ? ' · Eski parolalı kayıt' : ' · Bu Windows hesabıyla açılır'}</small></span>
        <button className="button" disabled={busy || active} onClick={() => open(item)}>Aç</button>
        {!active && <a className="button" href={`/api/recordings/${item.id}/download`} download>Şifreli indir</a>}
        {!active && <button className="button" disabled={busy} onClick={() => void downloadMitm(item)}>Şifresini çöz · .mitm indir</button>}
      </li>)}</ul>}
    </div>
  </dialog>
}
