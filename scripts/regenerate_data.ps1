# 一键重新生成三个停车场数据库
# 运行前请先停止所有 ParkingLotAgent 实例

Set-Location $PSScriptRoot/..

Write-Host "重新生成停车场数据..." -ForegroundColor Green

python scripts/regenerate_data.py `
    --name "购物中心停车场" --total-spots 800 --floors 4 `
    --spots-per-floor "200,200,200,200" --nev-weights "55,25,12,8" `
    --db-path instances/parking_a/data/parking_a.db --days 120

python scripts/regenerate_data.py `
    --name "科技园停车场" --total-spots 500 --floors 3 `
    --spots-per-floor "167,167,166" --nev-weights "50,30,12,8" `
    --db-path instances/parking_b/data/parking_b.db --days 120

python scripts/regenerate_data.py `
    --name "社区停车场" --total-spots 1200 --floors 5 `
    --spots-per-floor "240,240,240,240,240" --nev-weights "60,20,12,8" `
    --db-path instances/parking_c/data/parking_c.db --days 120

Write-Host "`n全部完成。" -ForegroundColor Green
