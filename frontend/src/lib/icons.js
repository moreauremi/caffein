// SPDX-License-Identifier: AGPL-3.0-or-later
// Icônes désignées par leur nom côté serveur (modules, pages, chiffres clés, actions).
// Liste fermée pour garder une interface légère ; un nom inconnu affiche une icône générique.
import {
  AlertTriangle, Ban, Bell, Blocks, Bot, Boxes, Briefcase, Building2, Calculator, CalendarCheck, CalendarClock, CalendarDays,
  CalendarOff, CheckCircle2, CircleDashed, ClipboardCheck, ClipboardList, Clock3, Cog, Contact, Factory, FileSignature,
  FileStack, FileText, FolderKanban, Gauge, Handshake, Hammer, House, Inbox, Info, Landmark, Layers, LayoutDashboard,
  ListChecks, ListTree, Network, Package, PackageCheck, PackageMinus, PackageOpen, PackagePlus, Palette, PenTool, Percent,
  PieChart, Play, Plus, ReceiptText, Route, Ruler, Scale, Send, Settings, ShieldCheck, ShoppingBag, ShoppingCart, Sparkles,
  Square, Store, Tag, Target, Timer, TrendingUp, Truck, Upload, UserCheck, UserPlus, UserRound, Users, UsersRound,
  Wallet, Warehouse, Workflow, Wrench, X,
} from 'lucide-react'

export const ICONS = {
  AlertTriangle, Ban, Bell, Blocks, Bot, Boxes, Briefcase, Building2, Calculator, CalendarCheck, CalendarClock, CalendarDays,
  CalendarOff, CheckCircle2, CircleDashed, ClipboardCheck, ClipboardList, Clock3, Cog, Contact, Factory, FileSignature,
  FileStack, FileText, FolderKanban, Gauge, Handshake, Hammer, House, Inbox, Info, Landmark, Layers, LayoutDashboard,
  ListChecks, ListTree, Network, Package, PackageCheck, PackageMinus, PackageOpen, PackagePlus, Palette, PenTool, Percent,
  PieChart, Play, Plus, ReceiptText, Route, Ruler, Scale, Send, Settings, ShieldCheck, ShoppingBag, ShoppingCart, Sparkles,
  Square, Store, Tag, Target, Timer, TrendingUp, Truck, Upload, UserCheck, UserPlus, UserRound, Users, UsersRound,
  Wallet, Warehouse, Workflow, Wrench, X,
}

export function iconFor(name) {
  return ICONS[name] || CircleDashed
}
