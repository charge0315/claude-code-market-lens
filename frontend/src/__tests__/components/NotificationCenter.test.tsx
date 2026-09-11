import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { NotificationCenter } from '@/components/notify/NotificationCenter';
import { fetchNotifications, markNotificationRead } from '@/lib/api/notifications';
import { subscribeWs, type WsHandlers, type WsSubscription } from '@/lib/realtime/ws';
import {
  disablePushNotifications,
  enablePushNotifications,
  isPushEnabled,
  isPushSupported,
} from '@/lib/push/registerServiceWorker';
import type { AppNotification } from '@/lib/api/notifications';

jest.mock('@/lib/api/notifications', () => ({
  ...jest.requireActual('@/lib/api/notifications'),
  fetchNotifications: jest.fn(),
  markNotificationRead: jest.fn(),
}));
jest.mock('@/lib/realtime/ws');
jest.mock('@/lib/push/registerServiceWorker');

const mockFetchNotifications = fetchNotifications as jest.MockedFunction<typeof fetchNotifications>;
const mockMarkNotificationRead = markNotificationRead as jest.MockedFunction<typeof markNotificationRead>;
const mockSubscribeWs = subscribeWs as jest.MockedFunction<typeof subscribeWs>;
const mockIsPushSupported = isPushSupported as jest.MockedFunction<typeof isPushSupported>;
const mockIsPushEnabled = isPushEnabled as jest.MockedFunction<typeof isPushEnabled>;
const mockEnablePush = enablePushNotifications as jest.MockedFunction<typeof enablePushNotifications>;
const mockDisablePush = disablePushNotifications as jest.MockedFunction<typeof disablePushNotifications>;

const NOTIFICATION: AppNotification = {
  notification_id: 'n1',
  run_date: '2026-06-02',
  ticker: '7203',
  kind: 'trim',
  channel: 'in_app',
  body: JSON.stringify({ symbol: '7203', action: 'trim', entry: null, stop: 2800, target: 3200, confidence: 72, rationale: 'テスト根拠' }),
  created_at: '2026-06-02T10:00:00+09:00',
  read_at: null,
};

function setupWs(): { handlers: WsHandlers; close: jest.Mock } {
  let handlers!: WsHandlers;
  const close = jest.fn();
  mockSubscribeWs.mockImplementation((_path, h) => {
    handlers = h;
    return { close } as WsSubscription;
  });
  return { get handlers() { return handlers; }, close };
}

describe('NotificationCenter', () => {
  beforeEach(() => {
    mockIsPushSupported.mockReturnValue(false);
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it('通知が無ければ空メッセージを出す', async () => {
    mockFetchNotifications.mockResolvedValue([]);
    setupWs();

    render(<NotificationCenter />);

    expect(await screen.findByText('通知はありません')).toBeInTheDocument();
  });

  it('取得済みの通知一覧を表示する', async () => {
    mockFetchNotifications.mockResolvedValue([NOTIFICATION]);
    setupWs();

    render(<NotificationCenter />);

    expect(await screen.findByText('7203')).toBeInTheDocument();
    expect(screen.getByText('一部利確')).toBeInTheDocument();
    expect(screen.getByText('テスト根拠')).toBeInTheDocument();
  });

  it('WS 経由で新規通知を受け取ると一覧に反映する', async () => {
    mockFetchNotifications.mockResolvedValue([]);
    const ws = setupWs();

    render(<NotificationCenter />);
    await waitFor(() => expect(mockSubscribeWs).toHaveBeenCalled());

    act(() => {
      ws.handlers.onMessage(NOTIFICATION);
      ws.handlers.onStatus?.('open');
    });

    expect(await screen.findByText('7203')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('ライブ接続中');
  });

  it('既読にするボタンで既読化する', async () => {
    mockFetchNotifications.mockResolvedValue([NOTIFICATION]);
    mockMarkNotificationRead.mockResolvedValue({ ...NOTIFICATION, read_at: '2026-06-02T10:05:00+09:00' });
    setupWs();
    const user = userEvent.setup();

    render(<NotificationCenter />);
    await user.click(await screen.findByRole('button', { name: '既読にする' }));

    await waitFor(() => expect(mockMarkNotificationRead).toHaveBeenCalledWith('n1'));
    await waitFor(() => expect(screen.queryByRole('button', { name: '既読にする' })).not.toBeInTheDocument());
  });

  it('Push 未対応ブラウザではトグルボタンを表示しない', async () => {
    mockFetchNotifications.mockResolvedValue([]);
    mockIsPushSupported.mockReturnValue(false);
    setupWs();

    render(<NotificationCenter />);
    await waitFor(() => expect(mockFetchNotifications).toHaveBeenCalled());

    expect(screen.queryByRole('button', { name: /Push 通知/ })).not.toBeInTheDocument();
  });

  it('Push 対応ブラウザでは有効化トグルが動作する', async () => {
    mockFetchNotifications.mockResolvedValue([]);
    mockIsPushSupported.mockReturnValue(true);
    mockIsPushEnabled.mockResolvedValue(false);
    mockEnablePush.mockResolvedValue(true);
    setupWs();
    const user = userEvent.setup();

    render(<NotificationCenter />);
    const toggle = await screen.findByRole('button', { name: 'Push 通知を有効化' });

    await user.click(toggle);

    await waitFor(() => expect(mockEnablePush).toHaveBeenCalled());
    expect(await screen.findByRole('button', { name: 'Push 通知を無効化' })).toBeInTheDocument();
  });

  it('有効時のトグルクリックで無効化する', async () => {
    mockFetchNotifications.mockResolvedValue([]);
    mockIsPushSupported.mockReturnValue(true);
    mockIsPushEnabled.mockResolvedValue(true);
    mockDisablePush.mockResolvedValue(undefined);
    setupWs();
    const user = userEvent.setup();

    render(<NotificationCenter />);
    const toggle = await screen.findByRole('button', { name: 'Push 通知を無効化' });

    await user.click(toggle);

    await waitFor(() => expect(mockDisablePush).toHaveBeenCalled());
    expect(await screen.findByRole('button', { name: 'Push 通知を有効化' })).toBeInTheDocument();
  });

  it('取得失敗でエラーメッセージを出す', async () => {
    mockFetchNotifications.mockRejectedValue(new Error('boom'));
    setupWs();

    render(<NotificationCenter />);

    expect(await screen.findByText('通知一覧の取得に失敗しました')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchNotifications.mockResolvedValue([NOTIFICATION]);
    setupWs();

    const { container } = render(<NotificationCenter />);
    await screen.findByText('7203');

    expect(await axe(container)).toHaveNoViolations();
  });
});
