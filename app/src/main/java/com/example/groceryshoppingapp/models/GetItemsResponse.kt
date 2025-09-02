package com.example.groceryshoppingapp.models

data class GetItemsResponse(
    val success: Boolean,
    val shopDocId: String,
    val items: List<Item>
)