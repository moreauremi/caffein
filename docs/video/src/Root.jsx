// SPDX-License-Identifier: AGPL-3.0-or-later
// Une seule composition : la démonstration de « Mes vues », en 1080p à 30 images par seconde.
import { Composition } from 'remotion'
import { DURATION, FPS, MesVues } from './MesVues'

export function Root() {
  return (
    <Composition id="MesVues" component={MesVues} durationInFrames={DURATION} fps={FPS} width={1920} height={1080} />
  )
}
