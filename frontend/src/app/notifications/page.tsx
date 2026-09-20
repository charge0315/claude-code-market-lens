import type { ReactNode } from 'react';
import { PageShell } from '@/components/ui/PageShell';
import { NotificationCenter } from '@/components/notify/NotificationCenter';
import { DailyNoteReview } from '@/components/notes/DailyNoteReview';

export default function NotificationsPage(): ReactNode {
  return (
    <PageShell title="通知センター">
      <section>
        <h2>本日のnote下書き</h2>
        <p>AIが本日のピック分析結果から生成した有料note記事の下書き。確認・編集して承認し、note.comへは手動投稿する。</p>
        <DailyNoteReview />
      </section>
      <section>
        <h2>通知</h2>
        <p>Web Push（VAPID）購読管理、通知履歴。デスクトップ常駐で受信（PWA 化は対象外）。</p>
        <NotificationCenter />
      </section>
    </PageShell>
  );
}
