package com.example.groceryshoppingapp.util

import com.example.groceryshoppingapp.models.CartItem
import com.example.groceryshoppingapp.models.Item

object CartManager {
    // Maintain cart items separately for each shop by shopId (UUID = String)
    private val shopCarts = mutableMapOf<String, MutableList<CartItem>>()

    fun addToCart(item: Item, shopId: String) {
        val cart = shopCarts.getOrPut(shopId) { mutableListOf() }
        val existing = cart.find { it.item.id == item.id }
        if (existing != null) {
            existing.quantity++
        } else {
            cart.add(CartItem(item, 1))
        }
    }

    fun getCart(shopId: String): List<CartItem> {
        return shopCarts[shopId] ?: emptyList()
    }

    fun getAllCarts(): Map<String, List<CartItem>> = shopCarts

    fun clearCart(shopId: String?) {
        shopCarts.remove(shopId)
    }

    fun clearAllCarts() {
        shopCarts.clear()
    }

    fun updateCartItem(shopId: String, updatedItem: CartItem) {
        val cart = shopCarts[shopId]
        cart?.let {
            val index = it.indexOfFirst { it.item.id == updatedItem.item.id }
            if (index >= 0) it[index] = updatedItem
        }
    }

    // ✅ changed Int → String
    fun removeItem(shopId: String, itemId: String) {
        val cart = shopCarts[shopId]
        cart?.removeIf { it.item.id == itemId }
    }

    fun getCartTotal(shopId: String): Double {
        return shopCarts[shopId]?.sumOf { it.item.price * it.quantity } ?: 0.0
    }

    fun isCartEmpty(shopId: String): Boolean {
        return shopCarts[shopId].isNullOrEmpty()
    }

    // ✅ changed Int → String
    fun incrementQuantity(shopId: String, itemId: String) {
        val cart = shopCarts[shopId]
        cart?.find { it.item.id == itemId }?.let { it.quantity++ }
    }

    // ✅ changed Int → String
    fun decrementQuantity(shopId: String, itemId: String) {
        val cart = shopCarts[shopId]
        val item = cart?.find { it.item.id == itemId }
        if (item != null) {
            if (item.quantity > 1) {
                item.quantity--
            } else {
                cart.remove(item)
            }
        }
    }
}
