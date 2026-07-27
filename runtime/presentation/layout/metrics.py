from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class UiMetrics:
    page_margin: int = 12
    page_section_gap: int = 10
    card_padding: int = 10
    sidebar_width: int = 152
    icon_size: int = 16
    badge_size: int = 18
    login_card_min_width: int = 320
    login_card_max_width: int = 390
    toast_min_width: int = 300
    toast_max_width: int = 430
    notifications_min_width: int = 340
    notifications_max_width: int = 460
    notifications_min_height: int = 230
    notifications_max_height: int = 430
    notifications_row_height: int = 52
    notifications_popup_fallback_height: int = 240
    progress_thin_height: int = 8
    input_min_width_sm: int = 96
    input_min_width_md: int = 118
    input_min_width_lg: int = 190
    compact_button_min_width: int = 84
    action_button_min_width: int = 96
    action_button_min_height: int = 24
    control_min_height: int = 24
    qty_field_max_width: int = 72
    transition_progress_min_width: int = 120
    transition_progress_max_width: int = 160
    branch_list_min_height: int = 140
    app_window_min_width: int = 1040
    app_window_min_height: int = 600
    app_window_fallback_width: int = 1280
    app_window_fallback_height: int = 720
    app_window_fallback_min_width: int = 760
    app_window_fallback_min_height: int = 440
    org_window_min_width: int = 720
    org_window_min_height: int = 460
    org_window_fallback_width: int = 900
    org_window_fallback_height: int = 560
    org_window_fallback_min_width: int = 600
    org_window_fallback_min_height: int = 420
    edit_product_dialog_min_width: int = 360
    edit_product_dialog_min_height: int = 200
    edit_product_dialog_max_width: int = 520
    edit_product_dialog_max_height: int = 340
    stored_products_dialog_min_width: int = 480
    stored_products_dialog_min_height: int = 320
    stored_products_dialog_max_width: int = 700
    stored_products_dialog_max_height: int = 520
    usage_products_dialog_min_width: int = 500
    usage_products_dialog_min_height: int = 340
    usage_products_dialog_max_width: int = 760
    usage_products_dialog_max_height: int = 560
    settings_dialog_min_width: int = 580
    settings_dialog_min_height: int = 360
    settings_dialog_max_width: int = 760
    settings_dialog_max_height: int = 520


UI_METRICS = UiMetrics()
