<script setup lang="ts">
import { onLaunch } from '@dcloudio/uni-app'
import { clientUserId } from './utils/request'

onLaunch(() => {
  console.log('[StudyHelper] client_user_id:', clientUserId)
})
</script>

<style>
/* 全局样式 */
page {
  font-family: -apple-system, BlinkMacSystemFont, 'Helvetica Neue', sans-serif;
  background-color: #f5f5f5;
}
</style>

<!-- H5 端全局引入 KaTeX CSS -->
<!-- #ifdef H5 -->
<style src="katex/dist/katex.min.css"></style>
<!-- #endif -->
