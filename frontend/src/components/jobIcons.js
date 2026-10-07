// SPDX-License-Identifier: AGPL-3.0-or-later
import { BellRing, CalendarClock, FileOutput, FolderTree, Mail, Newspaper, ScanLine, Send } from 'lucide-react'

// Pictogramme de chaque script d'automatisation
export const JOB_ICONS = {
  process_inbox: ScanLine,
  generate_pdf: FileOutput,
  send_invoice: Send,
  auto_reminders: BellRing,
  onboarding_emails: Mail,
  newsletter_notifications: Newspaper,
  fiscal_alerts: CalendarClock,
  setup_drive: FolderTree,
}
