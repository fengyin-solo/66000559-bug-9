<template>
  <div class="panel">
    <h4>📋 回测报告</h4>

    <template v-if="status==='success' && store.gridResult">
      <div class="report-params" v-if="store.reportConfig">
        参数：¥{{ store.reportConfig.lowerPrice }}–{{ store.reportConfig.upperPrice }} ·
        {{ store.reportConfig.gridCount }}格 ·
        每格¥{{ store.reportConfig.capitalPerGrid.toLocaleString() }} ·
        本金¥{{ store.reportConfig.initialCapital.toLocaleString() }}
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
          <span class="o-side" :class="o.side==='BUY'?'buy':'sell'">{{ o.side }}<em v-if="o.closing" class="o-tag">平仓</em></span>
          <span class="o-price">@¥{{ o.price }}</span>
          <span class="o-qty">{{ o.quantity.toFixed(2) }}</span>
          <span class="o-profit" :class="o.profit>=0?'profit':'loss'" v-if="o.side==='SELL'">{{ o.profit>=0?'+':'' }}¥{{ o.profit.toFixed(2) }}</span>
        </div>
      </div>
    </template>

    <div v-else-if="status==='loading'" class="state-box">
      <span class="spinner"></span>
      <span>正在运行回测…</span>
    </div>

    <div v-else-if="status==='error'" class="state-box error-box">
      <div class="err-title">⚠️ {{ store.errorMsg || '回测失败' }}</div>
      <div class="err-hint">请检查参数或后端服务后重新点击「运行回测」</div>
    </div>

    <div v-else class="state-box idle-box">暂无回测报告，设置参数后点击「运行回测」</div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from 'vue'
import * as echarts from 'echarts'
import { useTradingStore } from '../store/trading'
const store = useTradingStore()
const status = computed(() => store.status)
const eqChart = ref<HTMLDivElement>()
let inst: echarts.ECharts|null = null

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

// 结果切换：新结果重新初始化图表，结果清空时销毁，避免残留旧曲线
watch(() => store.gridResult, (r) => {
  if (!r) { inst?.dispose(); inst = null; return }
  setTimeout(() => {
    if (!eqChart.value) return
    if (!inst || inst.isDisposed()) inst = echarts.init(eqChart.value)
    updateEq()
  }, 50)
})

function onResize() { inst?.resize() }
window.addEventListener('resize', onResize)
onUnmounted(() => { window.removeEventListener('resize', onResize); inst?.dispose(); inst = null })
</script>

<style scoped>
.panel{background:#0f1535;border-radius:8px;padding:12px;border:1px solid #1e2a5a}
.panel h4{color:#4fc3f7;font-size:13px;margin-bottom:8px}
.report-params{font-size:10px;color:#94a3b8;background:#0a0e27;border-radius:4px;padding:4px 6px;margin-bottom:8px;line-height:1.5}
.metric-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}
.metric{text-align:center;padding:8px;background:#0a0e27;border-radius:6px}
.m-val{font-size:18px;font-weight:700}.m-val.profit{color:#22c55e}.m-val.loss{color:#ef4444}
.m-label{font-size:10px;color:#64748b;margin-top:2px}
.chart{width:100%;height:120px;margin-top:8px}
.order-row{display:flex;gap:8px;padding:3px 6px;font-size:11px;border-radius:3px;margin:1px 0}
.order-row.BUY{background:#22c55e15}.order-row.SELL{background:#ef444415}
.o-side{font-weight:700;min-width:30px}.o-side.buy{color:#22c55e}.o-side.sell{color:#ef4444}
.o-tag{font-style:normal;font-size:9px;color:#fbbf24;margin-left:3px;font-weight:400}
.o-price{color:#94a3b8}.o-qty{color:#64748b}.o-profit.profit{color:#22c55e}.o-profit.loss{color:#ef4444}
.section-title{font-size:11px;color:#64748b;margin:6px 0 4px}
.state-box{display:flex;align-items:center;justify-content:center;gap:8px;min-height:120px;padding:12px;font-size:12px;color:#64748b;text-align:center}
.idle-box{background:#0a0e27;border-radius:6px;line-height:1.6}
.error-box{flex-direction:column;gap:6px;background:#ef444410;border:1px solid #ef444444;border-radius:6px}
.err-title{color:#ef4444;font-size:12px;font-weight:600;line-height:1.5}
.err-hint{font-size:11px;color:#94a3b8}
.spinner{width:16px;height:16px;border:2px solid #1e2a5a;border-top-color:#4fc3f7;border-radius:50%;animation:spin 0.8s linear infinite;flex:none}
@keyframes spin{to{transform:rotate(360deg)}}
</style>
