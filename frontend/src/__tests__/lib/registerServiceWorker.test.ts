import { fetchVapidPublicKey, subscribePush, unsubscribePush } from '@/lib/api/notifications';
import {
  disablePushNotifications,
  enablePushNotifications,
  isPushEnabled,
  isPushSupported,
} from '@/lib/push/registerServiceWorker';

jest.mock('@/lib/api/notifications');

const mockFetchVapidPublicKey = fetchVapidPublicKey as jest.MockedFunction<typeof fetchVapidPublicKey>;
const mockSubscribePush = subscribePush as jest.MockedFunction<typeof subscribePush>;
const mockUnsubscribePush = unsubscribePush as jest.MockedFunction<typeof unsubscribePush>;

function defineServiceWorker(registration: unknown): void {
  Object.defineProperty(window.navigator, 'serviceWorker', {
    value: {
      register: jest.fn().mockResolvedValue(registration),
      ready: Promise.resolve(registration),
      getRegistration: jest.fn().mockResolvedValue(registration),
    },
    configurable: true,
  });
}

describe('registerServiceWorker', () => {
  const originalNotification = (global as unknown as { Notification?: unknown }).Notification;

  afterEach(() => {
    jest.clearAllMocks();
    // `in` 演算子はキーの存在だけを見るため、値を undefined にするだけでは
    // isPushSupported() の判定を戻せない。次のテストへ漏れないよう明示的に削除する。
    delete (window.navigator as unknown as Record<string, unknown>).serviceWorker;
    delete (window as unknown as Record<string, unknown>).PushManager;
    (global as unknown as { Notification?: unknown }).Notification = originalNotification;
  });

  describe('isPushSupported', () => {
    it('serviceWorker / PushManager が無ければ false', () => {
      expect(isPushSupported()).toBe(false);
    });

    it('両方あれば true', () => {
      defineServiceWorker({});
      (window as unknown as { PushManager: unknown }).PushManager = class {};

      expect(isPushSupported()).toBe(true);
    });
  });

  describe('enablePushNotifications', () => {
    it('非対応ブラウザでは false を返す', async () => {
      await expect(enablePushNotifications()).resolves.toBe(false);
    });

    it('VAPID 未設定なら false を返す', async () => {
      defineServiceWorker({});
      (window as unknown as { PushManager: unknown }).PushManager = class {};
      mockFetchVapidPublicKey.mockResolvedValue({ public_key: '' });

      await expect(enablePushNotifications()).resolves.toBe(false);
    });

    it('権限が拒否されたら false を返す', async () => {
      defineServiceWorker({});
      (window as unknown as { PushManager: unknown }).PushManager = class {};
      mockFetchVapidPublicKey.mockResolvedValue({ public_key: 'AAAA' });
      (global as unknown as { Notification: unknown }).Notification = {
        requestPermission: jest.fn().mockResolvedValue('denied'),
      };

      await expect(enablePushNotifications()).resolves.toBe(false);
    });

    it('許可されれば購読して true を返す', async () => {
      const subscription = {
        endpoint: 'https://push.example/a',
        toJSON: () => ({ keys: { p256dh: 'p', auth: 'a' } }),
      };
      defineServiceWorker({ pushManager: { subscribe: jest.fn().mockResolvedValue(subscription) } });
      (window as unknown as { PushManager: unknown }).PushManager = class {};
      mockFetchVapidPublicKey.mockResolvedValue({ public_key: 'AAAA' });
      (global as unknown as { Notification: unknown }).Notification = {
        requestPermission: jest.fn().mockResolvedValue('granted'),
      };
      mockSubscribePush.mockResolvedValue({ subscribed: true });

      await expect(enablePushNotifications()).resolves.toBe(true);
      expect(mockSubscribePush).toHaveBeenCalledWith(
        expect.objectContaining({ endpoint: 'https://push.example/a', p256dh: 'p', auth: 'a' }),
      );
    });
  });

  describe('isPushEnabled / disablePushNotifications', () => {
    it('購読が無ければ isPushEnabled は false', async () => {
      defineServiceWorker({ pushManager: { getSubscription: jest.fn().mockResolvedValue(undefined) } });
      (window as unknown as { PushManager: unknown }).PushManager = class {};

      await expect(isPushEnabled()).resolves.toBe(false);
    });

    it('購読があれば isPushEnabled は true', async () => {
      defineServiceWorker({ pushManager: { getSubscription: jest.fn().mockResolvedValue({}) } });
      (window as unknown as { PushManager: unknown }).PushManager = class {};

      await expect(isPushEnabled()).resolves.toBe(true);
    });

    it('disablePushNotifications は購読解除して unsubscribePush を呼ぶ', async () => {
      const unsubscribe = jest.fn().mockResolvedValue(undefined);
      defineServiceWorker({
        pushManager: { getSubscription: jest.fn().mockResolvedValue({ endpoint: 'https://push.example/a', unsubscribe }) },
      });
      (window as unknown as { PushManager: unknown }).PushManager = class {};
      mockUnsubscribePush.mockResolvedValue({ unsubscribed: true });

      await disablePushNotifications();

      expect(mockUnsubscribePush).toHaveBeenCalledWith('https://push.example/a');
      expect(unsubscribe).toHaveBeenCalled();
    });
  });
});
