import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'
import type { Tick, OrderBook, GridConfig, GridResult } from '@/types'

export type BacktestStatus = 'idle' | 'loading' | 'success' | 'error'

const STORAGE_KEY = 'grid-backtest-report'

/** 重新进入页面时恢复上一份报告及其对应参数，刷新后不再回到空报告 */
function loadPersistedReport(): { result: GridResult; config: GridConfig } | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed?.result || !Array.isArray(parsed.result.orders) || !parsed?.config) return null
    return { result: parsed.result as GridResult, config: parsed.config as GridConfig }
  } catch {
    return null
  }
}

export const useTradingStore = defineStore('trading', () => {
  const ticks = ref<Tick[]>([])
  const orderBook = ref<OrderBook | null>(null)
  const gridResult = ref<GridResult | null>(null)
  const wsConnected = ref(false)
  const status = ref<BacktestStatus>('idle')
  const errorMsg = ref('')
  /** 当前报告对应的参数快照（始终与 gridResult 同一份回测结果） */
  const reportConfig = ref<GridConfig | null>(null)

  const persisted = loadPersistedReport()
  const config = ref<GridConfig>(persisted
    ? { ...persisted.config }
    : { lowerPrice: 95, upperPrice: 115, gridCount: 20, capitalPerGrid: 1000, initialCapital: 100000 })
  if (persisted) {
    gridResult.value = persisted.result
    reportConfig.value = persisted.config
    status.value = 'success'
  }

  const loading = computed(() => status.value === 'loading')

  let ws: WebSocket | null = null
  function connectWS() {
    ws = new WebSocket(`ws://${location.hostname}:8000/ws`)
    ws.onopen = () => { wsConnected.value = true }
    ws.onmessage = (e) => {
      try {
        const d = JSON.parse(e.data)
        if (d.ticks) ticks.value = d.ticks.slice(-60)
        if (d.orderBook) orderBook.value = d.orderBook
      } catch {}
    }
    ws.onclose = () => { wsConnected.value = false }
  }

  function formatError(err: unknown): string {
    if (axios.isAxiosError(err)) {
      if (err.response) {
        const data = err.response.data as { detail?: unknown } | undefined
        const detail = data?.detail
        if (typeof detail === 'string' && detail) return `回测失败（${err.response.status}）：${detail}`
        if (Array.isArray(detail) && detail.length) {
          const msg = detail.map((d: { msg?: string }) => d?.msg).filter(Boolean).join('；')
          if (msg) return `回测失败（${err.response.status}）：参数有误 - ${msg}`
        }
        return `回测失败：服务器返回错误（HTTP ${err.response.status}）`
      }
      if (err.request) return '回测失败：无法连接回测服务，请确认后端已启动（localhost:8000）'
      return `回测失败：${err.message}`
    }
    return err instanceof Error ? `回测失败：${err.message}` : '回测失败：未知错误'
  }

  async function runBacktest() {
    // 切换参数重新回测：先清掉上一份成交明细与曲线，避免新旧数据混显
    const params: GridConfig = { ...config.value }
    status.value = 'loading'
    errorMsg.value = ''
    gridResult.value = null
    reportConfig.value = null
    try {
      const { data } = await axios.post<GridResult>('/api/backtest', params)
      // 指标、曲线、明细统一绑定这一份返回结果；参数也以本次提交的快照为准
      gridResult.value = data
      reportConfig.value = params
      status.value = 'success'
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify({ result: data, config: params })) } catch {}
    } catch (err) {
      // 失败时写明原因并停止 loading，不再一直转圈
      status.value = 'error'
      errorMsg.value = formatError(err)
      gridResult.value = null
      try { localStorage.removeItem(STORAGE_KEY) } catch {}
    }
  }

  function disconnectWS() { ws?.close(); ws = null; wsConnected.value = false }

  return { loading, status, errorMsg, ticks, orderBook, gridResult, reportConfig, wsConnected, config, connectWS, runBacktest, disconnectWS }
})
