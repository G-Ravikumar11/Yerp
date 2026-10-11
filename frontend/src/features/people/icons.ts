import { Briefcase, Building2, Calculator, Droplets, HardHat, Ruler, Shield, Truck, Users, Wrench, Zap, type LucideIcon } from 'lucide-react'

/** The icons a department can carry. The name is what is stored; anything unknown falls back to a building. */
export const DEPARTMENT_ICONS: Record<string, LucideIcon> = { building: Building2, 'hard-hat': HardHat, wrench: Wrench, calculator: Calculator, users: Users, truck: Truck, zap: Zap, droplets: Droplets, shield: Shield, briefcase: Briefcase, ruler: Ruler }
export const DEPARTMENT_COLORS = ['#e8590c', '#2f9e44', '#1971c2', '#9c36b5', '#c2255c', '#0c8599', '#f08c00', '#495057']
export const iconOf = (name: string): LucideIcon => DEPARTMENT_ICONS[name] ?? Building2
