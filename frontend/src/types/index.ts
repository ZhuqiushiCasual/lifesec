export interface User {
  id: string;
  email: string;
  name: string | null;
  is_active: boolean;
  created_at: string;
}

export interface EventItem {
  id: string;
  user_id: string;
  type: string;
  content: string;
  entities: Record<string, any> | null;
  sentiment: string | null;
  sentiment_score: number | null;
  tags: string[] | null;
  voice_source: boolean;
  recorded_at: string;
  created_at: string;
}

export interface FinanceTxn {
  id: string;
  user_id: string;
  type: 'expense' | 'income' | 'asset' | 'liability';
  amount: number;
  currency: string;
  category: string;
  counterparty: string | null;
  account: string | null;
  note: string | null;
  voice_source: boolean;
  recorded_at: string;
  created_at: string;
}

export interface Insight {
  id: string;
  user_id: string;
  title: string;
  summary: string;
  impact: string | null;
  category: string;
  topics: string[] | null;
  importance: number | null;
  source_url: string | null;
  source_name: string | null;
  published_at: string | null;
  created_at: string;
}

export interface Digest {
  id: string;
  user_id: string;
  date: string;
  score: number | null;
  highlights: Record<string, any> | null;
  problems: Record<string, any> | null;
  suggestions: Record<string, any> | null;
  trends: Record<string, any> | null;
  created_at: string;
}

export interface WeeklyChart {
  type: string;
  title: string;
  unit: string;
  color: string;
  data: number[];
  summary: string;
  target?: number;
}

export interface WeeklyTrendResponse {
  week_start: string;
  days: string[];
  day_labels: string[];
  charts: WeeklyChart[];
  health_events: Array<{
    id: string;
    type: string;
    content: string;
    recorded_at: string;
  }>;
}

export interface TodayBoard {
  greeting: string;
  date: string;
  today_event_count: number;
  sport_done: boolean;
  mood: string | null;
  water_warning: boolean;
  recent_events: Array<{
    id: string;
    type: string;
    content: string;
    recorded_at: string;
  }>;
  latest_insights: Array<{
    id: string;
    title: string;
    category: string;
    summary: string;
  }>;
  has_latest_digest: boolean;
  digest_date: string | null;
}
