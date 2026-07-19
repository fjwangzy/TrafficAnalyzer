const KIB = 1024

export function manualChunks(id) {
  if (!id.includes('node_modules')) return undefined
  if (id.includes('/ol/')) return 'map-vendor'
  if (id.includes('/recharts/') || id.includes('/d3-')) return 'chart-vendor'
  if (id.includes('/@tanstack/react-query/')) return 'query-vendor'
  if (id.includes('/react/') || id.includes('/react-dom/') || id.includes('/react-router') || id.includes('/scheduler/')) return 'react-vendor'
  return 'vendor'
}

export function bundleBudgetPlugin({ entryKib = 350, chunkKib = 750 } = {}) {
  return {
    name: 'console2-bundle-budget',
    apply: 'build',
    generateBundle(_options, bundle) {
      for (const output of Object.values(bundle)) {
        if (output.type !== 'chunk') continue
        const limit = (output.isEntry ? entryKib : chunkKib) * KIB
        if (output.code.length > limit) {
          this.error(`${output.fileName} 超出 ${output.isEntry ? '入口' : '分块'}预算：${Math.ceil(output.code.length / KIB)} KiB > ${limit / KIB} KiB`)
        }
      }
    },
  }
}
