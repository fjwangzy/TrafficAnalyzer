export function detectorVideoStreamSrc(pipeline, retryNonce) {
  const registered = typeof pipeline?.video_stream_url === 'string' ? pipeline.video_stream_url.trim() : ''
  if (!registered) return ''
  try {
    const url = new URL(registered)
    if (!['http:', 'https:'].includes(url.protocol)) return ''
    if (retryNonce !== undefined) url.searchParams.set('retry', String(retryNonce))
    return url.toString()
  } catch {
    return ''
  }
}
