import { configure } from '@testing-library/react'

// How long findBy… waits for what a test expects to appear (see vite.config.ts).
configure({ asyncUtilTimeout: 5000 })
