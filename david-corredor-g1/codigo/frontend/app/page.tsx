'use client'

import { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  ArrowUpRight,
  Bot,
  Check,
  ChevronDown,
  Clock3,
  Command,
  Download,
  ExternalLink,
  Filter,
  Inbox,
  Layers3,
  Menu,
  MessageSquareText,
  MoreHorizontal,
  PanelRight,
  Play,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  X,
  Zap,
} from 'lucide-react'
import { api, type ApiTicket, type ApiIncident, type ApiStats } from '@/lib/api'

// Mapea un ticket del backend al shape que usa la UI
function mapTicket(t: ApiTicket) {
  return {
    id: t.ticket_id,
    customer: t.customer_id,
    title: t.triage?.summary ?? t.text,
    category: t.triage?.category ?? 'Otro',
    module: t.triage?.product_or_module ?? 'Unknown',
    priority: t.triage?.priority ?? 'P4',
    confidence: Math.round((t.triage?.confidence ?? 0) * 100),
    time: t.created_at,
    region: t.region,
    incident: t.incident_group_id ?? '—',
    sentiment: t.triage?.sentiment ?? 'neutral',
    action: t.triage?.suggested_action ?? '',
    response: t.triage?.suggested_response ?? '',
    users: t.text,
    requires_human_review: t.triage?.requires_human_review ?? false,
  }
}

function mapIncident(i: ApiIncident) {
  return {
    id: i.incident_group_id,
    title: i.title,
    count: i.ticket_count,
    priority: i.highest_priority,
    region: i.affected_region,
    impact: `${i.affected_customers.length} clientes · ${i.affected_regions.length} regiones`,
    major: i.major_incident_candidate,
  }
}

const priorityStyles: Record<string, string> = { P1: 'priority-p1', P2: 'priority-p2', P3: 'priority-p3', P4: 'priority-p4' }

export default function Page() {
  const [selectedId, setSelectedId] = useState<string>('')
  const [activeTab, setActiveTab] = useState<'queue' | 'incidents'>('queue')
  const [priority, setPriority] = useState('Todas')
  const [category, setCategory] = useState('Todas')
  const [search, setSearch] = useState('')
  const [showComposer, setShowComposer] = useState(false)
  const [processed, setProcessed] = useState(false)

  // Data fetching — poll cada 5s con AbortController
  const [tickets, setTickets] = useState<ReturnType<typeof mapTicket>[]>([])
  const [incidents, setIncidents] = useState<ReturnType<typeof mapIncident>[]>([])
  const [stats, setStats] = useState<ApiStats | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let aborted = false
    const controller = new AbortController()

    async function load() {
      try {
        const [queueData, incidentsData, statsData] = await Promise.all([
          api.queue(),
          api.incidents(),
          api.stats(),
        ])
        if (aborted) return
        setTickets(queueData.map(mapTicket))
        setIncidents(incidentsData.map(mapIncident))
        setStats(statsData)
        setLoading(false)
        if (!selectedId && queueData.length > 0) setSelectedId(queueData[0].ticket_id)
      } catch (err) {
        if (!aborted) {
          console.error('Error cargando datos del backend:', err)
          setLoading(false)
        }
      }
    }

    load()
    const interval = setInterval(load, 5000)
    return () => {
      aborted = true
      controller.abort()
      clearInterval(interval)
    }
  }, [selectedId])

  const filteredTickets = useMemo(() => tickets.filter((ticket) => {
    const matchesPriority = priority === 'Todas' || ticket.priority === priority
    const matchesCategory = category === 'Todas' || ticket.category === category
    const term = search.toLowerCase()
    return matchesPriority && matchesCategory && (!term || `${ticket.id} ${ticket.title} ${ticket.customer}`.toLowerCase().includes(term))
  }), [priority, category, search])
  const selected = tickets.find((ticket) => ticket.id === selectedId) ?? tickets[0] ?? null

  return (
    <main className="atlas-shell">
      <aside className="sidebar">
        <div className="brand"><div className="brand-mark"><Zap size={18} fill="currentColor" /></div><div><strong>ATLAS</strong><span>CONTROL ROOM</span></div></div>
        <div className="war-room-status"><span className="status-dot" /> WAR ROOM ACTIVA <span className="status-time">08:40 UTC</span></div>
        <nav className="nav-list" aria-label="Navegación principal">
          <button className="nav-item active"><Inbox size={17} /> Cola de triage <span>{tickets.length}</span></button>
          <button className="nav-item" onClick={() => setActiveTab('incidents')}><AlertTriangle size={17} /> Incidentes <span className="nav-alert">{incidents.length}</span></button>
          <button className="nav-item"><Layers3 size={17} /> Todos los tickets</button>
          <button className="nav-item"><ShieldCheck size={17} /> Auditoría</button>
        </nav>
        <div className="sidebar-section"><p className="eyebrow">VISTAS GUARDADAS</p><button className="saved-view"><span className="view-dot red" /> P1 críticos <span>24</span></button><button className="saved-view"><span className="view-dot amber" /> Revisión humana <span>63</span></button><button className="saved-view"><span className="view-dot violet" /> Sin grupo <span>408</span></button></div>
        <div className="sidebar-bottom"><div className="model-card"><div className="model-icon"><Bot size={16} /></div><div><strong>GLM 5.2</strong><span>Motor operativo</span></div><span className="online-dot" /></div><div className="user-row"><div className="avatar">LR</div><div><strong>Lucía R.</strong><span>Incident commander</span></div><MoreHorizontal size={17} /></div></div>
      </aside>

      <section className="main-content">
        <header className="topbar"><div className="breadcrumbs"><span>ATLAS CLOUD</span><ChevronDown size={14} /><strong>Control Room</strong></div><div className="top-actions"><button className="icon-btn" aria-label="Buscar"><Command size={16} /></button><button className="icon-btn" aria-label="Notificaciones"><MessageSquareText size={16} /><i /></button><button className="button secondary" onClick={() => setShowComposer(true)}><Plus size={16} /> Probar ticket</button></div></header>
        <div className="workspace">
          <div className="page-heading"><div><p className="kicker"><span className="live-pulse" /> OPERACIONES EN TIEMPO REAL</p><h1>Hola, Lucía <span className="wave">✦</span></h1><p className="subheading">Esto es lo que requiere atención ahora.</p></div><div className="sla-card"><div className="sla-icon"><Clock3 size={17} /></div><div><span>PRÓXIMO SLA CRÍTICO</span><strong>01:20:00</strong></div><small>10:00 UTC</small></div></div>
          <div className="metric-grid"><Metric label="Tickets pendientes" value={stats ? String(stats.total_tickets) : '...'} delta="+18x" note="vs. volumen normal" tone="red" /><Metric label="P1 + P2 en cola" value={stats ? String(stats.by_priority.P1 + stats.by_priority.P2) : '...'} delta={stats ? String(stats.requires_human_review) : '0'} note="requieren atención" tone="amber" /><Metric label="Incidentes activos" value={stats ? String(stats.total_incidents) : '...'} delta={stats ? String(stats.major_incidents) : '0'} note="candidato mayor" tone="violet" /><Metric label="Procesados por IA" value="98,4%" delta="↑ 2,1%" note="confianza promedio" tone="cyan" /></div>
          <div className="section-tabs"><div className="tabs"><button className={activeTab === 'queue' ? 'tab active' : 'tab'} onClick={() => setActiveTab('queue')}>Cola priorizada <span>{tickets.length}</span></button><button className={activeTab === 'incidents' ? 'tab active' : 'tab'} onClick={() => setActiveTab('incidents')}>Incidentes <span>{incidents.length}</span></button></div><button className="text-button"><Download size={15} /> Exportar reporte</button></div>
          {activeTab === 'queue' ? (
            <div className="queue-layout">
              <section className="queue-panel">
                <div className="toolbar">
                  <div className="search-box">
                    <Search size={16} />
                    <input aria-label="Buscar tickets" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Buscar ticket, cliente o texto..." />
                  </div>
                  <div className="filters">
                    <select aria-label="Filtrar por prioridad" value={priority} onChange={(e) => setPriority(e.target.value)}>
                      <option>Todas</option><option>P1</option><option>P2</option><option>P3</option><option>P4</option>
                    </select>
                    <select aria-label="Filtrar por categoría" value={category} onChange={(e) => setCategory(e.target.value)}>
                      <option>Todas</option><option>Cuenta y acceso</option><option>Disponibilidad y rendimiento</option><option>Integraciones</option><option>Datos y exportación</option><option>Facturación</option><option>Solicitud de función</option>
                    </select>
                    <button className="filter-btn"><Filter size={15} /> Filtros <span>2</span></button>
                  </div>
                </div>
                <div className="queue-head">
                  <span>{filteredTickets.length} tickets visibles</span>
                  <button className="sort-button">Prioridad <ChevronDown size={14} /></button>
                </div>
                <div className="ticket-list">
                  {filteredTickets.map((ticket) => (
                    <button key={ticket.id} className={`ticket-row ${selectedId === ticket.id ? 'selected' : ''}`} onClick={() => setSelectedId(ticket.id)}>
                      <span className={`priority-badge ${priorityStyles[ticket.priority]}`}>{ticket.priority}</span>
                      <div className="ticket-main">
                        <div className="ticket-meta"><strong>{ticket.id}</strong><span>{ticket.customer}</span><span className="ticket-time">{ticket.time}</span></div>
                        <p>{ticket.title}</p>
                        <div className="ticket-tags"><span>{ticket.category}</span><span>{ticket.module}</span>{ticket.incident !== '—' && <span className="incident-tag"><AlertTriangle size={11} /> {ticket.incident}</span>}</div>
                      </div>
                      <div className="confidence"><span>{ticket.confidence}%</span><small>confianza</small></div>
                      <ArrowUpRight className="row-arrow" size={16} />
                    </button>
                  ))}
                </div>
              </section>
              {selected && <TicketDetail ticket={selected} />}
            </div>
          ) : (
            <IncidentView incidents={incidents} onSelect={(id) => { setActiveTab('queue'); setSelectedId(id) }} />
          )}
        </div>
      </section>
      {showComposer && <Composer onClose={() => setShowComposer(false)} processed={processed} onProcess={() => setProcessed(true)} />}
    </main>
  )
}

function Metric({ label, value, delta, note, tone }: { label: string; value: string; delta: string; note: string; tone: string }) { return <div className="metric-card"><div className={`metric-icon ${tone}`}><ActivityIcon tone={tone} /></div><div className="metric-copy"><span>{label}</span><strong>{value}</strong><small><b className={tone}>{delta}</b> {note}</small></div></div> }
function ActivityIcon({ tone }: { tone: string }) { return tone === 'red' ? <AlertTriangle size={17} /> : tone === 'amber' ? <Clock3 size={17} /> : tone === 'violet' ? <Layers3 size={17} /> : <Bot size={17} /> }
function TicketDetail({ ticket }: { ticket: NonNullable<typeof tickets[number]> }) { return <aside className="detail-panel"><div className="detail-header"><div><span className={`priority-badge ${priorityStyles[ticket.priority]}`}>{ticket.priority} · {ticket.priority === 'P1' ? 'Crítica' : ticket.priority === 'P2' ? 'Alta' : ticket.priority === 'P3' ? 'Normal' : 'Baja'}</span><h2>{ticket.id}</h2></div><button className="icon-btn"><MoreHorizontal size={17} /></button></div><div className="customer-line"><div className="avatar square">{ticket.customer.slice(0, 2)}</div><div><strong>{ticket.customer}</strong><span>Enterprise · {ticket.region}</span></div><button className="icon-btn"><ExternalLink size={15} /></button></div><div className="detail-scroll"><div className="detail-block"><span className="label">TEXTO ORIGINAL</span><p className="original-text">“{ticket.title}”</p></div><div className="detail-grid"><DetailItem label="Categoría" value={ticket.category} /><DetailItem label="Módulo" value={ticket.module} /><DetailItem label="Sentimiento" value={ticket.sentiment} /><DetailItem label="Grupo" value={ticket.incident} /></div><div className="ai-summary"><div className="ai-title"><Sparkles size={15} /> RESUMEN DE GLM 5.2 <span>94%</span></div><p>{ticket.title} El impacto requiere atención prioritaria y seguimiento del equipo responsable.</p></div><div className="detail-block"><span className="label">ACCIÓN SUGERIDA</span><p>{ticket.action}</p></div><div className="detail-block"><span className="label">BORRADOR DE RESPUESTA</span><div className="response-box"><p>{ticket.response}</p><button className="copy-button"><Check size={13} /> Copiar respuesta</button></div></div></div><div className="detail-footer"><div className="review-state"><span className="check-circle"><Check size={12} /></span><div><strong>Sin revisión humana</strong><small>Confianza suficiente · {ticket.confidence}%</small></div></div><button className="button primary">Asignar <ArrowUpRight size={15} /></button></div></aside> }
function DetailItem({ label, value }: { label: string; value: string }) { return <div className="detail-item"><span>{label}</span><strong>{value}</strong></div> }
function IncidentView({ onSelect, incidents }: { onSelect: (id: string) => void; incidents: typeof tickets[number][] }) { return <div className="incident-grid">{incidents.length > 0 ? incidents.map((incident) => <article className="incident-card" key={incident.id}><div className="incident-card-head"><span className={`priority-badge ${priorityStyles[incident.priority]}`}>{incident.priority}</span>{incident.major && <span className="major-badge"><AlertTriangle size={12} /> Candidato a mayor</span>}<button className="icon-btn"><MoreHorizontal size={16} /></button></div><p className="incident-id">{incident.id}</p><h2>{incident.title}</h2><div className="incident-stats"><div><strong>{incident.count}</strong><span>tickets relacionados</span></div><div><strong>{incident.region}</strong><span>región principal</span></div></div><div className="impact-bar"><span style={{ width: `${Math.min(100, incident.count * 4)}%` }} /></div><p className="impact-copy">{incident.impact}</p><button className="incident-link" onClick={() => onSelect(incident.id)}>Ver tickets relacionados <ArrowUpRight size={15} /></button></article>) : null}<article className="incident-empty"><div className="empty-icon"><Layers3 size={19} /></div><h3>Correlación en curso</h3><p>El motor está analizando tickets sin grupo para encontrar nuevos patrones.</p><button className="button secondary"><RefreshCw size={15} /> Actualizar análisis</button></article></div> }
function Composer({ onClose, processed, onProcess }: { onClose: () => void; processed: boolean; onProcess: (text: string) => void }) {
  const [text, setText] = useState('Desde esta mañana, 2.000 usuarios no pueden iniciar sesión con SSO después del despliegue.')
  const [result, setResult] = useState<{ category: string; priority: string; confidence: number } | null>(null)
  const [busy, setBusy] = useState(false)

  async function handleProcess() {
    setBusy(true)
    try {
      const res = await api.classifyManual({ text })
      const r = res.result as { category: string; priority: string; confidence: number }
      setResult({ category: r.category, priority: r.priority, confidence: Math.round(r.confidence * 100) })
      onProcess(text)
    } catch (err) {
      console.error('Error clasificando ticket:', err)
      setResult(null)
    } finally {
      setBusy(false)
    }
  }

  return <div className="modal-backdrop" onClick={onClose}><section className="composer" onClick={(e) => e.stopPropagation()}><div className="composer-head"><div><span className="kicker"><Sparkles size={13} /> TRIAGE MANUAL</span><h2>Probar un ticket</h2><p>Ejecuta el pipeline de clasificación con GLM 5.2.</p></div><button className="icon-btn" onClick={onClose}><X size={17} /></button></div><label>Texto del ticket<textarea placeholder="Describe el problema del cliente..." value={text} onChange={(e) => setText(e.target.value)} /></label>{result && <div className="processed-result"><div className="result-check"><Check size={17} /></div><div><strong>Ticket clasificado correctamente</strong><p>{result.priority} · {result.category} · {result.confidence}% confianza</p></div></div>}<div className="composer-actions"><button className="button secondary" onClick={onClose}>Cancelar</button><button className="button primary" onClick={handleProcess} disabled={busy}><Play size={15} /> {busy ? 'Procesando...' : processed ? 'Procesar de nuevo' : 'Ejecutar triage'}</button></div></section></div> }
