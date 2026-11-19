import { Capacitor, registerPlugin } from '@capacitor/core'

/**
 * Whether the phone itself says its position is being supplied by a mock-location app. Only the phone app can know (Android's
 * isFromMockProvider on the position; on iOS, the signs of a jailbroken phone), so the answer comes from a native plugin,
 * `MockLocation`, when the build has one. On the website, or in a build without it, there is nothing to ask and the answer is
 * no: the server then goes by the position, its accuracy and the fence alone, as it always has.
 */
interface MockLocationPlugin {
  check(): Promise<{ mock: boolean }>
}

const plugin = registerPlugin<MockLocationPlugin>('MockLocation')

export async function reportsMockLocation(): Promise<boolean> {
  if (!Capacitor.isNativePlatform() || !Capacitor.isPluginAvailable('MockLocation')) return false
  try {
    return (await plugin.check()).mock === true
  } catch {
    return false
  }
}
