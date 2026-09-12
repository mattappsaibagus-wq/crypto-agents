const COINGECKO = 'https://api.coingecko.com/api/v3'

function json(body: unknown, status = 200, cache = 'no-store') {
  return Response.json(body, {
    status,
    headers: { 'Cache-Control': cache },
  })
}

async function coinGecko(path: string) {
  const response = await fetch(`${COINGECKO}${path}`, {
    headers: { accept: 'application/json', 'user-agent': 'HadakaCrypto/1.0' },
  })
  if (!response.ok) throw new Error(`CoinGecko returned ${response.status}`)
  return response.json()
}

export default async (request: Request) => {
  if (request.method !== 'GET') return json({ error: 'Method not allowed' }, 405)

  const params = new URL(request.url).searchParams
  const symbol = (params.get('symbol') || '').trim().toUpperCase()
  const days = Number(params.get('days') || 1)
  if (!/^[A-Z0-9._-]{1,20}$/.test(symbol) || ![1, 7, 30].includes(days)) {
    return json({ error: 'Invalid coin or timeframe' }, 400)
  }

  try {
    const search = await coinGecko(`/search?query=${encodeURIComponent(symbol)}`)
    const matches = (search.coins || []).filter(
      (coin: { symbol?: string }) => coin.symbol?.toUpperCase() === symbol,
    )
    matches.sort(
      (a: { market_cap_rank?: number }, b: { market_cap_rank?: number }) =>
        (a.market_cap_rank || Number.MAX_SAFE_INTEGER) -
        (b.market_cap_rank || Number.MAX_SAFE_INTEGER),
    )
    const coin = matches[0]
    if (!coin?.id) return json({ error: 'Coin not found' }, 404, 'public, s-maxage=300')

    const marketPromise = coinGecko(
      `/coins/markets?vs_currency=usd&ids=${encodeURIComponent(coin.id)}&price_change_percentage=7d`,
    ).catch(() => [])

    let chartType = 'candlestick'
    let points: unknown[] = []
    try {
      const ohlc = await coinGecko(
        `/coins/${encodeURIComponent(coin.id)}/ohlc?vs_currency=usd&days=${days}`,
      )
      if (Array.isArray(ohlc) && ohlc.length) points = ohlc
    } catch {
      // Some new or thinly traded assets do not expose OHLC data.
    }

    if (!points.length) {
      const history = await coinGecko(
        `/coins/${encodeURIComponent(coin.id)}/market_chart?vs_currency=usd&days=${days}`,
      )
      points = Array.isArray(history.prices) ? history.prices : []
      chartType = 'line'
    }

    if (!points.length) return json({ error: 'No chart history is available' }, 404, 'public, s-maxage=300')

    const marketRows = await marketPromise
    const market = marketRows[0] || {}
    return json(
      {
        coin: { id: coin.id, name: coin.name, symbol },
        chartType,
        points,
        stats: {
          dailyChange: market.price_change_percentage_24h,
          weeklyChange: market.price_change_percentage_7d_in_currency,
          high24h: market.high_24h,
          low24h: market.low_24h,
        },
      },
      200,
      'public, s-maxage=300, stale-while-revalidate=3600',
    )
  } catch (error) {
    console.error('Coin market lookup failed', error instanceof Error ? error.message : 'Unknown error')
    return json({ error: 'Market data is temporarily unavailable' }, 503, 'public, s-maxage=30')
  }
}

export const config = { path: '/api/coin-market' }
