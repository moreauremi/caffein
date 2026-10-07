// SPDX-License-Identifier: AGPL-3.0-or-later
import { Suspense } from 'react'
import { Outlet } from 'react-router-dom'
import { AppProvider, useApp } from '../context/AppContext'
import Navbar from './navbar/Navbar'
import SettingsModal from './SettingsModal'
import { Spinner } from './ui'

function Shell() {
  const { settingsTab } = useApp()
  return (
    <>
      <Navbar />
      <main className="container">
        <Suspense fallback={<div className="page"><Spinner /></div>}>
          <Outlet />
        </Suspense>
      </main>
      {settingsTab && <SettingsModal />}
    </>
  )
}

export default function AppLayout() {
  return (
    <AppProvider>
      <Shell />
    </AppProvider>
  )
}
