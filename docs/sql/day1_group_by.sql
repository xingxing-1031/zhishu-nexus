-- 目标：统计最近 30 天每个渠道的已支付订单数和销售额
-- 排序：销售额从高到低

SELECT
    channel,
    COUNT(*) AS paid_order_count,
    SUM(amount) AS sales_amount
FROM orders
WHERE status = 'paid'
  AND created_at >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY channel
ORDER BY sales_amount DESC;
