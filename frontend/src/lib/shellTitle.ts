import { createContext, useContext } from 'react'

/**
 * The title the phone app's top bar already shows for the screen being looked at. A page that begins with the same words
 * (its own big heading) leaves them out on the phone, so the name is not said twice, one above the other. Empty on the
 * website, whose frame has no title bar.
 */
export const ShellTitle = createContext('')
export const useShellTitle = () => useContext(ShellTitle)
