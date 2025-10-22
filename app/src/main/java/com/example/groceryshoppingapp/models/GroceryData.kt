package com.example.groceryshoppingapp

data class GroceryData(
    val categories: List<Category>
)

data class Category(
    val name: String,
    val items: List<GroceryItem>
)

data class GroceryItem(
    val name: String,
    val description: String,
    val image: String
)
