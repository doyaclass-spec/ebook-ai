-- Supabase에서 실행할 SQL
-- Table Editor → SQL Editor에 붙여넣고 실행

create table if not exists ebooks (
  id          text primary key,
  title       text not null,
  author      text,
  theme       text default 'green',
  block_count integer default 0,
  pdf_size_kb integer default 0,
  book_json   text not null,
  created_at  timestamptz default now()
);

-- 최신순 조회를 위한 인덱스
create index if not exists idx_ebooks_created_at on ebooks(created_at desc);

-- RLS 비활성화 (서버에서 service key로 접근)
alter table ebooks disable row level security;
