package com.example.groceryshoppingapp

import com.example.groceryshoppingapp.models.Item
import com.example.groceryshoppingapp.models.Shop
import java.util.UUID

object SampleData {

    private val shopNames = listOf(
        "Fresh Basket", "Urban Market", "Organic Haven", "Quick Buy", "Daily Delight",
        "Grocery Hub", "Nature’s Best", "Healthy Mart", "Neighborhood Store", "Budget Bazaar"
    )

    private val addresses = listOf(
        "12 Elm Street", "45 Oak Avenue", "78 Pine Lane", "101 Maple Blvd",
        "222 Cedar Road", "333 Birch Street", "444 Spruce Drive", "555 Aspen Way",
        "678 Poplar Path", "789 Willow Square"
    )

    private val phoneNumbers = listOf(
        "9876543210", "8765432109", "7654321098", "6543210987", "5432109876",
        "4321098765", "3210987654", "2109876543", "1098765432", "9988776655"
    )

    fun getShops(): List<Shop> {
        return (1..10).map { index ->
            Shop(
                id =  UUID.randomUUID().toString(),
                name = shopNames.getOrNull(index - 1) ?: "Shop $index",
                address = addresses.getOrNull(index - 1) ?: "Address $index",
                contact = phoneNumbers.getOrNull(index - 1) ?: "999999999$index",
                shopkeeper_id = 200 + (index % 3)

            )
        }
    }

    private val itemNames = listOf(
        "Apples", "Bananas", "Milk", "Bread", "Eggs", "Butter", "Rice", "Pasta",
        "Chicken", "Tomatoes", "Onions", "Potatoes", "Cereal", "Cheese", "Yogurt",
        "Coffee", "Tea", "Juice", "Sugar", "Salt", "Oil", "Flour", "Beans", "Spinach", "Carrots"
    )


    // Add this inside the SampleData object
    fun getShopNameById(shopId: String): String {
        return getShops().find { it.id == shopId }?.name ?: "Unknown Shop"
    }


    fun getItemsForShop(shopId: String): List<Item> {
        return (1..20).map { index ->
            val itemName = itemNames.getOrNull(index - 1) ?: "Item $index"
            val price = when (itemName) {
                "Apples", "Bananas", "Tomatoes", "Onions", "Potatoes", "Spinach", "Carrots" -> (20..80).random()
                "Milk", "Bread", "Butter", "Yogurt", "Cheese" -> (30..100).random()
                "Chicken" -> (120..250).random()
                "Rice", "Pasta", "Cereal", "Flour", "Beans" -> (40..120).random()
                "Coffee", "Tea", "Juice", "Sugar", "Salt", "Oil" -> (30..200).random()
                else -> (10..150).random()
            }.toDouble()

            Item(
                id = UUID.randomUUID().toString(),
                name = itemName,
                price = price,
                description = "Fresh and high-quality $itemName available at affordable price.",
                shopid = shopId,
                stockQuantity = (5..50).random()
            )
        }
    }
}
