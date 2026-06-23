import axios from 'axios';
import { API_BASE } from '../config';

const api = axios.create({
  baseURL: API_BASE,
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
});

export const events = {
  create: (data: { content: string; recorded_at?: string }) =>
    api.post('/api/events', data),
  list: (page = 1, pageSize = 20) =>
    api.get('/api/events', { params: { page, page_size: pageSize } }),
  delete: (id: string) => api.delete(`/api/events/${id}`),
};

export const finance = {
  createTxn: (data: { content: string }) =>
    api.post('/api/finance/txns', data),
  listTxns: (page = 1) =>
    api.get('/api/finance/txns', { params: { page } }),
  deleteTxn: (id: string) => api.delete(`/api/finance/txns/${id}`),
  getSummary: () => api.get('/api/finance/summary'),
  getAssets: () => api.get('/api/finance/assets'),
};

export const insights = {
  list: (category?: string) =>
    api.get('/api/insights', { params: { category } }),
  get: (id: string) => api.get(`/api/insights/${id}`),
};

export const digests = {
  latest: () => api.get('/api/digests/latest'),
  byDate: (date: string) => api.get('/api/digests', { params: { date } }),
};

export const board = {
  today: () => api.get('/api/board/today'),
};

export const memory = {
  weekly: () => api.get('/api/memory/weekly'),
  trends: (days = 30) => api.get('/api/memory/trends', { params: { days } }),
  review: (date: string) => api.get('/api/memory/review', { params: { date } }),
};

export const voice = {
  transcribe: (audioBase64: string, format = 'wav') =>
    api.post('/api/voice/transcribe', { audio_base64: audioBase64, format }),
};

export default api;
