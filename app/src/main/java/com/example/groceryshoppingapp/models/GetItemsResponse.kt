
package com.example.groceryshoppingapp.models

data class GetItemsResponse(
    val success: Boolean,
    val shop: Shop?,            // same Shop model reused
    val items: List<Item>
)
