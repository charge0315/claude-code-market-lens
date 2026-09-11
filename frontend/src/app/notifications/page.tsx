import type { ReactNode } from 'react';
import { PageShell } from '@/components/ui/PageShell';
import { NotificationCenter } from '@/components/notify/NotificationCenter';

export default function NotificationsPage(): ReactNode {
  return (
    <PageShell title="通知センター" phase="P7">
      <p>Web Push（VAPID）購読管理、通知履歴。デスクトップ常駐で受信（PWA 化は対象外）。</p>
      <NotificationCenter />
    </PageShell>
  );
}
