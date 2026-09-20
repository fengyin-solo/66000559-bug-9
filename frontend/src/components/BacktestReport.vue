<template>
  <div class="panel">
    <h4>📋 回测报告</h4>

    <!-- 加载中 -->
    <div class="state-box loading" v-if="store.loading">
      <span class="spinner"></span>
      <span>正在运行回测…</span>
    </div>

    <!-- 失败：写明原因，不再一直转圈 -->
    <div class="state-box error" v-else-if="store.error">
      <div class="err-msg">⚠️ {{ store.error }}</div>
      <el-button type="primary" size="small" @click="store.runBacktest()">重新回测</el-button>
    </div>

    <!-- 空报告 -->
    <div class="state-box empty" v-else-if="!store.gridResult">
      <span>暂无回测结果，请在上方配置参数后运行回测</span>
    </div>

    <template v-else>
      <div class="report-params" v-if="store.resultConfig">
        参数：下限 ¥{{ store.resultConfig.lowerPrice }} · 上限 ¥{{ store.resultConfig.upperPrice }}
        · {{ store.resultConfig.gridCount }} 格 · 每格 ¥{{ store.resultConfig.capitalPerGrid }}
        · 本金 ¥{{ store.resultConfig.initialCapital.toLocaleString() }}
      </div>
      <div class="metric-grid">
        <div class="metric">
          <div class="m-val" :class="store.gridResult.totalProfit>=0?'profit':'loss'">¥{{ store.gridResult.totalProfit.toFixed(2) }}</div>
          <div class="m-label">总盈亏</div>
        </div>
        <div class="metric"><div class="m-val" :class="store.gridResult.returnRate>=0?'profit':'loss'">{{ store.gridResult.returnRate.toFixed(2) }}%</div><div class="m-label">收益率</div></div>
        <div class="metric"><div class="m-val">{{ store.gridResult.sharpeRatio.toFixed(2) }}</div><div class="m-label">夏普比率</div></div>
        <div class="metric"><div class="m-val loss">{{ store.gridResult.maxDrawdown.toFixed(2) }}%</div><div class="m-label">最大回撤</div></div>
        <div class="metric"><div class="m-val">{{ store.gridResult.winRate.toFixed(1) }}%</div><div class="m-label">胜率</div></div>
        <div class="metric"><div class="m-val">{{ store.gridResult.orders.filter(o=>o.side==='SELL').length }}</div><div class="m-label">成交笔数</div></div>
      </div>
      <div ref="eqChart" class="chart"></div>
      <div class="order-list" v-if="store.gridResult.orders.length">
        <div class="section-title">最近成交</div>
        <div v-for="o in store.gridResult.orders.slice(-8).reverse()" :key="o.id" class="order-row" :class="o.side">
          <span class="o-side" :class="o.side.toLowerCase()">{{ o.side }}</span>
          <span class="o-price">@¥{{ o.price }}</span>
          <span class="o-qty">{{ o.quantity.toFixed(2) }}</span>
          <span class="o-profit" :class="o.profit>=0?'profit':'loss'" v-if="o.side==='SELL'">{{ o.profit>=0?'+':'' }}¥{{ o.profit.toFixed(2) }}</span>
        </div>
        <div class="section-title summary-row">
          <span>逐笔盈亏汇总（全部 {{ store.gridResult.orders.filter(o=>o.side==='SELL').length }} 笔平仓）</span>
          <span :class="profitSum>=0?'profit':'loss'">{{ profitSum>=0?'+':'' }}¥{{ profitSum.toFixed(2) }}</span>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import { useTradingStore } from '../store/trading'
const store = useTradingStore(); const eqChart = ref<HTMLDivElement>(); let inst: echarts.ECharts|null=null

// 明细逐笔盈亏汇总：与指标区总盈亏同源同一份结果，应完全相等
const profitSum = computed(() =>
  store.gridResult ? store.gridResult.orders.reduce((s, o) => s + o.profit, 0) : 0)

function updateEq() {
  if (!inst || !store.gridResult) return
  const eq = store.gridResult.equityCurve
  inst.setOption({
    backgroundColor:'transparent',grid:{left:45,right:10,top:5,bottom:20},
    xAxis:{type:'category',data:eq.map((_,i)=>i),show:false},
    yAxis:{type:'value',axisLabel:{color:'#94a3b8',fontSize:9}},
    series:[{type:'line',data:eq,symbol:'none',lineStyle:{color:'#4fc3f7',width:1},
      areaStyle:{color:new echarts.graphic.LinearGradient(0,0,0,1,[{offset:0,color:'rgba(79,195,247,0.2)'},{offset:1,color:'rgba(79,195,247,0)'}])}
    }],animation:false
  })
}

async function renderChart() {
  if (!store.gridResult) {
    inst?.dispose(); inst = null
    return
  }
  await nextTick() // 等待 v-if 展开后的 .chart 容器出现
  if (!eqChart.value) return
  if (!inst) inst = echarts.init(eqChart.value)
  updateEq()
}

// 首次结果（含刷新后恢复）到达时容器才渲染，必须在 onMounted/nextTick 后初始化
onMounted(renderChart)
watch(() => store.gridResult, renderChart)
onUnmounted(() => inst?.dispose())
</script>

<style scoped>
.panel{background:#0f1535;border-radius:8px;padding:12px;border:1px solid #1e2a5a}
.panel h4{color:#4fc3f7;font-size:13px;margin-bottom:8px}
.report-params{font-size:10px;color:#94a3b8;background:#0a0e27;border-radius:4px;padding:5px 7px;margin-bottom:8px;line-height:1.5}
.state-box{padding:24px 12px;text-align:center;font-size:12px;color:#64748b;display:flex;flex-direction:column;align-items:center;gap:10px}
.spinner{width:22px;height:22px;border:2px solid #1e2a5a;border-top-color:#4fc3f7;border-radius:50%;animation:spin 0.8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.err-msg{color:#ef4444;font-size:12px;line-height:1.6}
.metric-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}
.metric{text-align:center;padding:8px;background:#0a0e27;border-radius:6px}
.m-val{font-size:18px;font-weight:700}.m-val.profit{color:#22c55e}.m-val.loss{color:#ef4444}
.m-label{font-size:10px;color:#64748b;margin-top:2px}
.chart{width:100%;height:120px;margin-top:8px}
.order-row{display:flex;gap:8px;padding:3px 6px;font-size:11px;border-radius:3px;margin:1px 0}
.order-row.BUY{background:#22c55e15}.order-row.SELL{background:#ef444415}
.o-side{font-weight:700;min-width:30px}.o-side.buy{color:#22c55e}.o-side.sell{color:#ef4444}
.o-price{color:#94a3b8}.o-qty{color:#64748b}.o-profit{margin-left:auto}.o-profit.profit{color:#22c55e}.o-profit.loss{color:#ef4444}
.section-title{font-size:11px;color:#64748b;margin:6px 0 4px}
.summary-row{display:flex;justify-content:space-between;align-items:center;border-top:1px solid #1e2a5a;padding-top:6px;margin-top:6px}
.summary-row .profit{color:#22c55e}.summary-row .loss{color:#ef4444}
</style>
