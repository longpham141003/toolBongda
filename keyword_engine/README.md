# Keyword Engine — Domain Pack (config-driven)

Tách **engine** (logic generic, ổn định trong `.py`) khỏi **knowledge** (cấu hình
theo lĩnh vực, trong `packs/*.yaml`). Engine chỉ tiêu thụ pack; mọi danh từ thuộc
một lĩnh vực cụ thể (team, cầu thủ, pressing, sportsdb…) nằm trong YAML, không
nằm trong code.

## Phân giải pack — 3 tầng (ưu tiên trên xuống)

1. **project override** — `project_config_path` hoặc `<repo>/project.yaml`.
2. **`packs/{video_domain}.yaml`** — theo `video_domain` mà giai đoạn dựng
   video-context đã suy ra (ví dụ `football`).
3. **synthetic pack** — không khớp pack nào thì AI sinh pack rút gọn từ
   `video_context` (4 trường lõi: `entity_types`, `action_lexicon`,
   `source_routes`, `forbidden_contexts`), overlay lên `generic.yaml`, cache theo
   `script_hash` tại `scripts/domain_pack.ai.json`. AI lỗi → `packs/generic.yaml`.

## API (xem `domain_pack.py`)

| Hàm | Thay cho hardcode |
|---|---|
| `resolve_domain_pack(script, video_context, ...)` | (mới) phân giải 3 tầng |
| `resolve_action(text, pack)` | `_scene_action_hint` |
| `route_source(entity_type, scene_type, pack, slots)` | nhánh route TheSportsDB cứng |
| `build_scene_query(scene_type, slots, pack)` | template query trận đấu |
| `forbidden_for(pack)` | danh sách "cấm logo/wallpaper" trong prompt |
| `safe_fallback(slots, pack)` | (mới) keyword an toàn khi bí ảnh |

Slot thiếu → bỏ slot đó, không để chuỗi `{...}` lọt ra keyword cuối.

## Thêm một domain mới

Chỉ cần thêm **một file YAML** vào `packs/` — KHÔNG sửa code engine:

```yaml
domain: true-crime
language_out: en
entity_types:
  - { id: suspect, role: subject }
  - { id: location, role: context }
action_lexicon:
  - { match: ["điều tra", "investigate"], visual: "detective investigating crime scene" }
source_routes:
  - { default: null, source: google_images, filters: { date_min: "{video_year}" } }
forbidden_contexts: [logo, wallpaper, ai generated]
```

Đặt `video_domain: true-crime` (qua video-context AI) → engine tự nạp pack này.
Nếu chưa có file, tầng 3 sẽ nhờ AI sinh synthetic pack tạm thời.

## Recency (chống lẫn edition cũ)

`recency.anchor` (`competition_year` | `video_year`) + `source_routes[].filters.date_min`
quyết định mốc thời gian. Engine lưu `item["search_date_min"]` rồi chuyển thành
bộ lọc ngày Google Images (`tbs=cdr:1,cd_min:MM/DD/YYYY`) khi tải ảnh.

> Ngoài phạm vi (Phase 2): chấm điểm + acceptance gate trên **ảnh thực tế** trả về.
> `forbidden_for()` và `safe_fallback()` đã sẵn sàng để Phase 2 dùng lại.
