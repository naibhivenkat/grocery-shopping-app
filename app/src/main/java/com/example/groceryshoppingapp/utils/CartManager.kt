//package com.example.groceryshoppingapp.util
//
//import com.example.groceryshoppingapp.models.CartItem
//import com.example.groceryshoppingapp.models.Item
//
//object CartManager {
//    // Maintain cart items separately for each shop by shopId (UUID = String)
//    private val shopCarts = mutableMapOf<String, MutableList<CartItem>>()
//
//    fun addToCart(item: Item, shopId: String) {
//        val cart = shopCarts.getOrPut(shopId) { mutableListOf() }
//        val existing = cart.find { it.item.id == item.id }
//        if (existing != null) {
//            existing.quantity++
//        } else {
//            cart.add(CartItem(item, 1))
//        }
//    }
//
//    fun getCart(shopId: String): List<CartItem> {
//        return shopCarts[shopId] ?: emptyList()
//    }
//
//    fun getAllCarts(): Map<String, List<CartItem>> = shopCarts
//
//    fun clearCart(shopId: String?) {
//        shopCarts.remove(shopId)
//    }
//
//    fun clearAllCarts() {
//        shopCarts.clear()
//    }
//
//    fun updateCartItem(shopId: String, updatedItem: CartItem) {
//        val cart = shopCarts[shopId]
//        cart?.let {
//            val index = it.indexOfFirst { it.item.id == updatedItem.item.id }
//            if (index >= 0) it[index] = updatedItem
//        }
//    }
//
//    // ✅ changed Int → String
//    fun removeItem(shopId: String, itemId: String) {
//        val cart = shopCarts[shopId]
//        cart?.removeIf { it.item.id == itemId }
//    }
//
//    fun getCartTotal(shopId: String): Double {
//        return shopCarts[shopId]?.sumOf { it.item.price * it.quantity } ?: 0.0
//    }
//
//    fun isCartEmpty(shopId: String): Boolean {
//        return shopCarts[shopId].isNullOrEmpty()
//    }
//
//    // ✅ changed Int → String
//    fun incrementQuantity(shopId: String, itemId: String) {
//        val cart = shopCarts[shopId]
//        cart?.find { it.item.id == itemId }?.let { it.quantity++ }
//    }
//
//    // ✅ changed Int → String
//    fun decrementQuantity(shopId: String, itemId: String) {
//        val cart = shopCarts[shopId]
//        val item = cart?.find { it.item.id == itemId }
//        if (item != null) {
//            if (item.quantity > 1) {
//                item.quantity--
//            } else {
//                cart.remove(item)
//            }
//        }
//    }
//}
package com.example.groceryshoppingapp.util

import android.util.Log
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
            Log.d("CartManager", "Incremented quantity → shopId=$shopId, item=${item.name}, qty=${existing.quantity}")
        } else {
            cart.add(CartItem(item, 1))
            Log.d("CartManager", "Added new item → shopId=$shopId, item=${item.name}, qty=1")
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
            val index = it.indexOfFirst { it.item.id == updatedItem.item.id }
            if (index >= 0) {
                it[index] = updatedItem
                Log.d("CartManager", "Updated cart item → shopId=$shopId, item=${updatedItem.item.name}, qty=${updatedItem.quantity}")
            }
        }
    }

    fun removeItem(shopId: String, itemId: String) {
        val cart = shopCarts[shopId]
        val removed = cart?.removeIf { it.item.id == itemId } ?: false
        Log.d("CartManager", "Removed item → shopId=$shopId, itemId=$itemId, success=$removed")
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

    fun incrementQuantity(shopId: String, itemId: String) {
        val cart = shopCarts[shopId]
        val item = cart?.find { it.item.id == itemId }
        if (item != null) {
            item.quantity++
            Log.d("CartManager", "Incremented quantity → shopId=$shopId, item=${item.item.name}, qty=${item.quantity}")
        }
    }

    fun decrementQuantity(shopId: String, itemId: String) {
        val cart = shopCarts[shopId]
        val item = cart?.find { it.item.id == itemId }
        if (item != null) {
            if (item.quantity > 1) {
                item.quantity--
                Log.d("CartManager", "Decremented quantity → shopId=$shopId, item=${item.item.name}, qty=${item.quantity}")
            } else {
                cart.remove(item)
                Log.d("CartManager", "Removed item after reaching 0 → shopId=$shopId, item=${item.item.name}")
            }
        }
    }
}
