package com.example.groceryshoppingapp.util

import android.util.Log
import com.example.groceryshoppingapp.models.CartItem
import com.example.groceryshoppingapp.models.Item

object CartManager {
    // Maintain cart items separately for each shop by shopId (UUID = String)
    private val shopCarts = mutableMapOf<String, MutableList<CartItem>>()

    // Add to cart with optional quantity and unit (default 1 pcs)
    fun addToCart(item: Item, shopId: String, quantity: Double = 1.0, unit: String = "pcs") {
        val cart = shopCarts.getOrPut(shopId) { mutableListOf() }
        // Merge only if same item AND same unit
        val existing = cart.find { it.item.id == item.id && it.unit == unit }
        if (existing != null) {
            existing.quantity += quantity
            Log.d("CartManager", "Incremented quantity → shopId=$shopId, item=${item.name}, qty=${existing.quantity} $unit")
        } else {
            cart.add(CartItem(item, quantity, unit))
            Log.d("CartManager", "Added new item → shopId=$shopId, item=${item.name}, qty=$quantity $unit")
        }
    }

    fun getCart(shopId: String): List<CartItem> {
        val cart = shopCarts[shopId] ?: emptyList()
        Log.d("CartManager", "Fetching cart → shopId=$shopId, size=${cart.size}")
        return cart
    }

    fun getAllCarts(): Map<String, List<CartItem>> {
        Log.d("CartManager", "Fetching all carts → totalShops=${shopCarts.size}")
        return shopCarts
    }

    fun clearCart(shopId: String?) {
        if (shopId != null) {
            shopCarts.remove(shopId)
            Log.d("CartManager", "Cleared cart → shopId=$shopId")
        }
    }

    fun clearAllCarts() {
        shopCarts.clear()
        Log.d("CartManager", "Cleared ALL carts")
    }

    fun updateCartItem(shopId: String, updatedItem: CartItem) {
        val cart = shopCarts[shopId]
        cart?.let {
            val index = it.indexOfFirst { it.item.id == updatedItem.item.id && it.unit == updatedItem.unit }
            if (index >= 0) {
                it[index] = updatedItem
                Log.d("CartManager", "Updated cart item → shopId=$shopId, item=${updatedItem.item.name}, qty=${updatedItem.quantity} ${updatedItem.unit}")
            }
        }
    }

    fun removeItem(shopId: String, itemId: String, unit: String = "pcs") {
        val cart = shopCarts[shopId]
        val removed = cart?.removeIf { it.item.id == itemId && it.unit == unit } ?: false
        Log.d("CartManager", "Removed item → shopId=$shopId, itemId=$itemId, unit=$unit, success=$removed")
    }

    fun getCartTotal(shopId: String): Double {
        val total = shopCarts[shopId]?.sumOf { it.item.price * it.quantity } ?: 0.0
        Log.d("CartManager", "Cart total → shopId=$shopId, total=$total")
        return total
    }

    fun isCartEmpty(shopId: String): Boolean {
        val empty = shopCarts[shopId].isNullOrEmpty()
        Log.d("CartManager", "Check cart empty → shopId=$shopId, empty=$empty")
        return empty
    }

    fun incrementQuantity(shopId: String, itemId: String, unit: String = "pcs") {
        val cart = shopCarts[shopId]
        val item = cart?.find { it.item.id == itemId && it.unit == unit }
        if (item != null) {
            item.quantity++
            Log.d("CartManager", "Incremented quantity → shopId=$shopId, item=${item.item.name}, qty=${item.quantity} ${item.unit}")
        }
    }

    fun decrementQuantity(shopId: String, itemId: String, unit: String = "pcs") {
        val cart = shopCarts[shopId]
        val item = cart?.find { it.item.id == itemId && it.unit == unit }
        if (item != null) {
            if (item.quantity > 1) {
                item.quantity--
                Log.d("CartManager", "Decremented quantity → shopId=$shopId, item=${item.item.name}, qty=${item.quantity} ${item.unit}")
            } else {
                cart.remove(item)
                Log.d("CartManager", "Removed item after reaching 0 → shopId=$shopId, item=${item.item.name}")
            }
        }
    }
}
