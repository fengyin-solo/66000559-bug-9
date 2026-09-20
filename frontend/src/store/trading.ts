import { defineStore } from 'pinia'
import { ref } from 'vue'
import axios from 'axios'
import type { AxiosError } from 'axios'
import type { Tick, OrderBook, GridConfig, GridResult } from '@/types'

const RESULT_STORAGE_KEY = 'grid-backtest-result'
const CONFIG_STORAGE_KEY = 'grid-backtest-config'
const DEFAULT_CONFIG: GridConfig = { lowerPrice: 95, upperPrice: 115, gridCount: 20, capitalPerGrid: 1000, initialCapital: 100000 }

function isConfig(v: unknown): v is GridConfig {
  if (typeof v !== 'object' || v === null) return false
  const c = v as Record<string, unknown>
  return ['lowerPrice', 'upperPrice', 'gridCount', 'capitalPerGrid', 'initialCapital']
    .every((k) => typeof c[k] === 'number' && Number.isFinite(c[k]))
}

function isResult(v: unknown): v is GridResult {
  if (typeof v !== 'object' || v === null) return false
  const r = v as Record<string, unknown>
  return Array.isArray(r.orders) && Array.isArray(r.equityCurve)
    && typeof r.totalProfit === 'number' && typeof r.returnRate === 'number'
    && typeof r.sharpeRatio === 'number' && typeof r.maxDrawdown === 'number'
    && typeof r.winRate === 'number'
}

export const useTradingStore = defineStore('trading', () => {
  const loading = ref(false)
  const error = ref('')
  const ticks = ref<Tick[]>([])
  const orderBook = ref<OrderBook | null>(null)
  const gridResult = ref<GridResult | null>(null)
  const wsConnected = ref(false)
  // config：表单当前值；resultConfig：生成当前这份报告所用的参数快照
  const config = ref<GridConfig>({ ...DEFAULT_CONFIG })
  const resultConfig = ref<GridConfig | null>(null)

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
    const ax = err as AxiosError<{ detail?: string }>
    if (ax?.response) {
      const detail = ax.response.data?.detail
      if (typeof detail === 'string' && detail) return `回测失败：${detail}`
      return `回测失败：服务端返回错误（${ax.response.status}）`
    }
    if (ax?.request) return '回测失败：无法连接回测服务，请检查后端是否已启动'
    return `回测失败：${err instanceof Error ? err.message : '未知错误'}`
  }

  async function runBacktest() {
    // 开跑即清空旧报告与旧错误，避免上一份成交明细残留
    loading.value = true
    error.value = ''
    gridResult.value = null
    resultConfig.value = null
    try {
      const params = { ...config.value }
      const { data } = await axios.post<GridResult>('/api/backtest', params)
      // 成功后整份结果与其参数快照一起落库，指标/曲线/明细同源
      gridResult.value = data
      resultConfig.value = params
      localStorage.setItem(RESULT_STORAGE_KEY, JSON.stringify(data))
      localStorage.setItem(CONFIG_STORAGE_KEY, JSON.stringify(params))
    } catch (err) {
      // 失败写明原因，不再一直转圈；旧结果已在开跑时清空
      error.value = formatError(err)
    } finally {
      loading.value = false
    }
  }

  function restoreBacktest() {
    try {
      const rawResult = localStorage.getItem(RESULT_STORAGE_KEY)
      const rawConfig = localStorage.getItem(CONFIG_STORAGE_KEY)
      if (rawResult && rawConfig) {
        const savedResult = JSON.parse(rawResult)
        const savedConfig = JSON.parse(rawConfig)
        if (isResult(savedResult) && isConfig(savedConfig)) {
          gridResult.value = savedResult
          resultConfig.value = savedConfig
          config.value = { ...savedConfig } // 表单参数恢复成生成这份报告时的值
        }
      }
    } catch {
      // 持久化数据损坏时静默丢弃，回到空报告
      localStorage.removeItem(RESULT_STORAGE_KEY)
      localStorage.removeItem(CONFIG_STORAGE_KEY)
    }
  }

  function disconnectWS() { ws?.close(); ws = null; wsConnected.value = false }

  return { loading, error, ticks, orderBook, gridResult, resultConfig, wsConnected, config, connectWS, runBacktest, restoreBacktest, disconnectWS }
})
