// SPDX-License-Identifier: AGPL-3.0-or-later
// Icônes désignées par leur nom côté serveur (modules, pages, chiffres clés, actions).
// Liste fermée pour garder une interface légère ; un nom inconnu affiche une icône générique.
// Un module choisit ses icônes dans cette liste (voir docs/modules.md).
import {
  AlertTriangle, ArrowLeftRight, BadgeCheck, Ban, Banknote, Barcode, Bell, Blocks, Bot, Boxes, Briefcase, BriefcaseBusiness,
  Bug, Building, Building2, Calculator, CalendarCheck, CalendarClock, CalendarDays, CalendarOff, CalendarRange, Car,
  CheckCheck, CheckCircle2, CircleCheck, CircleDashed, ClipboardCheck, ClipboardList, ClipboardX, Clock3, Cog, Coins, Combine,
  Component, Contact, Container, Factory, FileSignature, FileStack, FileText, FileWarning, FlaskConical, FolderKanban,
  Forklift, Gauge, GraduationCap, Hammer, Handshake, HardHat, Hourglass, House, IdCard, Inbox, Info, Kanban, Landmark, Layers,
  LayoutDashboard, ListChecks, ListOrdered, ListTodo, ListTree, Mail, Megaphone, Microscope, Network, OctagonAlert, Package,
  PackageCheck, PackageMinus, PackageOpen, PackagePlus, PackageSearch, Palette, PenTool, Percent, PhoneCall, PieChart,
  PiggyBank, Plane, Play, Plus, Receipt, ReceiptText, Recycle, Route, Ruler, Scale, ScanBarcode, Send, Settings, Shapes,
  ShieldAlert, ShieldCheck, ShoppingBag, ShoppingBasket, ShoppingCart, Siren, Sparkles, Split, Square, SquareKanban,
  Stethoscope, Store, Tag, Target, Thermometer, Ticket, Timer, TrendingUp, Truck, Upload, UserCheck, UserCog, UserPlus,
  UserRound, Users, UsersRound, Wallet, Warehouse, Workflow, Wrench, X,
} from 'lucide-react'

export const ICONS = {
  AlertTriangle, ArrowLeftRight, BadgeCheck, Ban, Banknote, Barcode, Bell, Blocks, Bot, Boxes, Briefcase, BriefcaseBusiness,
  Bug, Building, Building2, Calculator, CalendarCheck, CalendarClock, CalendarDays, CalendarOff, CalendarRange, Car,
  CheckCheck, CheckCircle2, CircleCheck, CircleDashed, ClipboardCheck, ClipboardList, ClipboardX, Clock3, Cog, Coins, Combine,
  Component, Contact, Container, Factory, FileSignature, FileStack, FileText, FileWarning, FlaskConical, FolderKanban,
  Forklift, Gauge, GraduationCap, Hammer, Handshake, HardHat, Hourglass, House, IdCard, Inbox, Info, Kanban, Landmark, Layers,
  LayoutDashboard, ListChecks, ListOrdered, ListTodo, ListTree, Mail, Megaphone, Microscope, Network, OctagonAlert, Package,
  PackageCheck, PackageMinus, PackageOpen, PackagePlus, PackageSearch, Palette, PenTool, Percent, PhoneCall, PieChart,
  PiggyBank, Plane, Play, Plus, Receipt, ReceiptText, Recycle, Route, Ruler, Scale, ScanBarcode, Send, Settings, Shapes,
  ShieldAlert, ShieldCheck, ShoppingBag, ShoppingBasket, ShoppingCart, Siren, Sparkles, Split, Square, SquareKanban,
  Stethoscope, Store, Tag, Target, Thermometer, Ticket, Timer, TrendingUp, Truck, Upload, UserCheck, UserCog, UserPlus,
  UserRound, Users, UsersRound, Wallet, Warehouse, Workflow, Wrench, X,
}

export function iconFor(name) {
  return ICONS[name] || CircleDashed
}
