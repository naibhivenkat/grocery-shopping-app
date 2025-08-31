package com.example.groceryshoppingapp.models

import com.example.groceryshoppingapp.models.Item

data class AddItemsRequest(
    val shop_id: String,
    val items: List<Item>
)