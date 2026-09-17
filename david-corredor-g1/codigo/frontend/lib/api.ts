/**
 * API client para el backend de ATLAS.
 * Usa fetch nativo (cero dependencias) con tipado TypeScript.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? 'http://localhost:3001/api';

export interface ApiTicket {
  ticket_id: string;
  customer_id: string;
  created_at: string;
  region: string;
  text: string;
  triage?: {
    category: string;
    priority: string;
    sentiment: string;
    product_or_module: string;
    summary: string;
    suggested_action: string;
    suggested_response: string;
    confidence: number;
    requires_human_review: boolean;
  };
  status: string;
  incident_group_id?: string | null;
}

export interface ApiIncident {
  incident_group_id: string;
  title: string;
  ticket_count: number;
  highest_priority: string;
  affected_module: string;
  affected_region: string;
  summary: string;
  major_incident_candidate: boolean;
  ticket_ids: string[];
  affected_customers: string[];
  affected_regions: string[];
}

export interface ApiStats {
  total_tickets: number;
  by_priority: { P1: number; P2: number; P3: number; P4: number };
  total_incidents: number;
  major_incidents: number;
  requires_human_review: number;
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const api = {
  queue: (params?: { priority?: string; category?: string; region?: string; module?: string; incident_group_id?: string }) => {
    const qs = new URLSearchParams();
    if (params) Object.entries(params).forEach(([k, v]) => v && qs.set(k, v));
    return fetchJson<ApiTicket[]>(`${API_BASE}/control-room/queue?${qs}`);
  },

  ticketDetail: (id: string) => fetchJson<{ ticket: ApiTicket; audit: unknown[] }>(`${API_BASE}/control-room/tickets/${id}`),

  incidents: () => fetchJson<ApiIncident[]>(`${API_BASE}/control-room/incidents`),

  incidentDetail: (id: string) => fetchJson<{ incident: ApiIncident; tickets: ApiTicket[] }>(`${API_BASE}/control-room/incidents/${id}`),

  stats: () => fetchJson<ApiStats>(`${API_BASE}/control-room/stats`),

  classifyManual: (body: { text: string; customer_id?: string; region?: string }) =>
    fetchJson<{ ticket: ApiTicket; result: unknown }>(`${API_BASE}/control-room/classify-manual`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),

  ingest: (tickets: unknown[]) =>
    fetchJson<{ accepted: number; results: unknown[] }>(`${API_BASE}/tickets/ingest`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(tickets),
    }),

  correlate: () =>
    fetchJson<{ status: string; message: string }>(`${API_BASE}/control-room/correlate`, {
      method: 'POST',
    }),

  report: (ticketId: string) => fetchJson<unknown>(`${API_BASE}/reports/tickets/${ticketId}`),
};
